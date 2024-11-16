from flask import Flask, request, jsonify, render_template_string, send_file
import datetime
import ssl
import os
import time
import psutil
from datetime import timedelta
from collections import deque
import signal
import yaml
import socket
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO


app = Flask(__name__)
start_time = time.time()
current_dir = os.path.dirname(os.path.abspath(__file__))

battery_max_voltage = 5
battery_min_voltage = 2

#########################################################################################################
## persistance
# List to store logs
logs = [] 
log_persistence_interval = 20  # Number of entries before persisting to file
log_show_last_lines = 20
log_file = os.path.join(current_dir, 'logs/server.log')
db_file = os.path.join(current_dir, 'db/clientData.txt')
db_client_log_file = os.path.join(current_dir, 'db/clientLog.txt')

last_client_data = {
    'refresh_rate': 900,
    'battery_voltage': battery_max_voltage,
    'rssi': -100,
    'last_contact': 0
}
# In-memory database to store battery voltage and timestamp
client_data_db = {
    'battery_voltage': None,
    'rssi': None,
    'timestamp': None
}
# In-memory database to store the last 30 battery voltage and timestamp pairs
client_data_db = deque(maxlen=30)
client_log_db = deque(maxlen=30)

def get_last_n_lines_from_log(file_path, n):
    with open(file_path, 'r') as file:
        lines = file.readlines()
        file_logs = lines[-n:]

    formatted_logs = [f"{log['timestamp']} -- [{log['context']}] -- {log['info']}\n" for log in logs]
    combined_logs = file_logs + formatted_logs
    return combined_logs

def persist_log():
    with open(log_file, 'a') as f:
        for log in logs:
            f.write(f"{log['timestamp']} -- [{log['context']}] -- {log['info']}\n")
    logs.clear()

def add_log_entry(context, info):
    log_entry = {
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'context': context,
        'info': info
    }
    logs.append(log_entry)
    if len(logs) >= log_persistence_interval:
        persist_log()

def add_client_data_entry(battery_voltage, rssi):
    # get the last entry from the client_data_db and compare battery_voltage new and old values
    if client_data_db:
        last_entry = client_data_db[-1]
        if last_entry['battery_voltage'] != battery_voltage:
            entry = {
                'battery_voltage': battery_voltage,
                'rssi': rssi,
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            client_data_db.append(entry)
    else:
        entry = {
            'battery_voltage': battery_voltage,
            'rssi': rssi,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        client_data_db.append(entry)
    if len(client_data_db) >= log_persistence_interval:
        persist_client_data()

def persist_client_data():
    with open(db_file, 'a') as f:
        for entry in client_data_db:
            f.write(f"{entry['timestamp']} -- bVolt: {entry['battery_voltage']}, rssi: {entry['rssi']}\n")
    if len(client_data_db) > 1:
        last_entry = client_data_db.pop()
        client_data_db.clear()
        client_data_db.append(last_entry)

def add_client_log_entry(log_entry):
    # Append the new entry to the client_data_db
    client_log_db.append(log_entry)
    if len(client_log_db) >= log_persistence_interval:
        persist_client_log_data()

def persist_client_log_data():
    with open(db_client_log_file, 'a') as f:
        for entry in client_log_db:
            f.write(f"{entry}\n")
    if len(client_log_db) > 1:
        last_entry = client_log_db.pop()
        client_log_db.clear()
        client_log_db.append(last_entry)

# reading client data from the file
def reading_client_data():
    client_data_db_read = []
    if os.path.exists(db_file):
        with open(db_file, 'r') as f:
            lines = f.readlines()
            for line in lines:
                data = line.split(' -- ')
                battery_voltage = float(data[1].split(',')[0].split(': ')[1])
                rssi = int(data[1].split(',')[1].split(': ')[1])
                timestamp = data[0]
                entry = {
                    'battery_voltage': battery_voltage,
                    'rssi': rssi,
                    'timestamp': timestamp
                }
                client_data_db_read.append(entry)
    # combine client_data_db and client_data_db_read only if more than 1 entry in client_data_db
    if len(client_data_db) > 1:
        client_data_db_read.extend(client_data_db)
    # sort data in client_data_db by timestamp
    client_data_db_read = sorted(client_data_db_read, key=lambda x: x['timestamp'])
    return client_data_db_read

#########################################################################################################
## configuration
# get the config file at current_dir/config.yaml
config_file = os.path.join(current_dir, 'config.yaml')
if os.path.exists(config_file):
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
        config_image_path = config['image_path']
        config_image_modification = config['image_modification']
        config_refresh_time = config['refresh_time']
        battery_max_voltage = config['battery_max_voltage']
        battery_min_voltage = config['battery_min_voltage']
else:
    config = {
        'image_path': 'images/screen.bmp',
        'image_modification': True,        
        'refresh_time': 900,
        'battery_max_voltage': 4.76,
        'battery_min_voltage': 3.3
    }
    with open(config_file, 'w') as f:
        yaml.safe_dump(config, f)
    print("Config file not found. Created a new one with default values.")
    print("Please restart the server after configuring the settings in config.yaml")
    exit(0)

#########################################################################################################
## bmp modification
# In-memory object to store the last sent image as a blob
current_orig_image = None
current_send_image = None
def getBatteryIcon(battery):
    battery = int(battery)
    if battery > 80:
        return "\uf240"
    elif battery > 60:
        return "\uf241"
    elif battery > 40:
        return "\uf242"
    elif battery > 20:
        return "\uf243"
    else:
        return "\uf244"
# Modify the footer background to black and the font to white
def add_footer_to_image(src_image, wifi_percentage, battery_percentage):
    # Load the source image
    img = Image.open(src_image)
    footer_height = 35
    # Resize the source image to make space for the footer
    img = img.crop((0, 0, img.width, img.height - footer_height))
    # Create a new image with extra space for the footer
    new_img = Image.new('1', (img.width, img.height + footer_height), color=0)  # '1' mode for 1-bit pixels, black and white
    
    # Paste the original image onto the new image
    new_img.paste(img, (0, 0))
    
    # Initialize ImageDraw
    d = ImageDraw.Draw(new_img)
    
    # Load fonts
    try:
        icon_font = ImageFont.truetype("web/fontawesome-webfont.ttf", 24)
        text_font = ImageFont.truetype("DejaVuSans.ttf", 14)
    except IOError:
        icon_font = ImageFont.load_default()
        text_font = ImageFont.load_default()
    
    # Define positions
    text_line_height = 7
    symbol_line_height = 4
    wifi_icon_position = (10, img.height + symbol_line_height)
    wifi_text_position = (50, img.height + text_line_height)
    battery_icon_position = (100, img.height + symbol_line_height)
    battery_text_position = (140, img.height + text_line_height)
    date_time_position = (img.width - 130, img.height + text_line_height)
    
    # Draw WiFi icon and percentage
    wifi_icon = "\uf1eb"
    d.text(wifi_icon_position, wifi_icon, fill=1, font=icon_font)  # fill=1 for white
    d.text(wifi_text_position, f"{round(wifi_percentage)}%", fill=1, font=text_font)  # fill=1 for white
    
    # Draw battery icon and percentage
    battery_icon = getBatteryIcon(battery_percentage)
    d.text(battery_icon_position, battery_icon, fill=1, font=icon_font)  # fill=1 for white
    d.text(battery_text_position, f"{round(battery_percentage)}%", fill=1, font=text_font)  # fill=1 for white
    
    # Draw date and time
    date_time = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    d.text(date_time_position, date_time, fill=1, font=text_font)  # fill=1 for white
    
    # Save the new image as BMP
    # Save the new image to a BytesIO object
    img_io = BytesIO()
    new_img.save(img_io, format="BMP")
    img_io.seek(0)
    
    # Manually adjust the BMP header
    img_io.seek(54)
    # Example: Set the color palette to black and white
    img_io.write(bytes([0, 0, 0, 0, 255, 255, 255, 0]))
    img_io.seek(0)

    return img_io

def get_and_modify_image():
    global config_image_path
    # Example usage
    wifi_percentage = getWifiSignalStrength(last_client_data['rssi'])
    battery_percentage = getBatteryState(last_client_data['battery_voltage'])
    return add_footer_to_image(config_image_path,wifi_percentage, battery_percentage)

def get_no_image():
        # Create a blank image with white background
    img = Image.new('1', (800, 480), color=1)  # '1' mode for 1-bit pixels, black and white
    
    # Initialize ImageDraw
    d = ImageDraw.Draw(img)
    
    # Load font
    try:
        text_font = ImageFont.truetype("DejaVuSans.ttf", 24)
    except IOError:
        text_font = ImageFont.load_default()
    
    # Define text position and content
    text = "No image available" 
    date_time = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    text = f"{text}\n{date_time}"
    text_bbox = d.textbbox((0, 0), text, font=text_font)
    text_width, text_height = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
    text_position = ((img.width - text_width) // 2, (img.height - text_height) // 2)
    
    # Draw text on the image
    d.text(text_position, text, fill=0, font=text_font)  # fill=0 for black
    
    # Save the image to a BytesIO object
    img_io = BytesIO()
    img.save(img_io, format="BMP")
    img_io.seek(0)
    return img_io
#########################################################################################################
## helper
def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip
# get the ip address of the server after startup of script
server_ip = get_ip_address()
print(f"Server is running on IP: {server_ip}")

# calculate battery state
def getBatteryState(battery_voltage):
    battery_state = round(((float(battery_voltage) - battery_min_voltage) / (battery_max_voltage - battery_min_voltage)) * 100, 1)
    if battery_state > 100:
        battery_state = 100
    elif battery_state < 0:
        battery_state = 0
    return battery_state

# calculate wifi signal strength
def getWifiSignalStrength(rssi):
    if rssi <= -100:
        quality = 0
    elif rssi >= -50:
        quality = 100
    else:
        quality = 2 * (rssi + 100)
    return quality

#########################################################################################################
## web server
## specific BMP serving

@app.route('/image/screen.bmp', methods=['GET'])
def serve_image_screen():
    global current_send_image
    # Log the request with timestamp and context
    add_log_entry('Request received at /image/screen.bmp', f'serving image for IP: {request.remote_addr}')
    return send_file(BytesIO(current_send_image.getvalue()), mimetype='image/bmp')

@app.route('/image/screen1.bmp', methods=['GET'])
def serve_image_screen1():
    global current_send_image
    # Log the request with timestamp and context
    add_log_entry('Request received at /image/screen1.bmp', f'serving image for IP: {request.remote_addr}')
    return send_file(BytesIO(current_send_image.getvalue()), mimetype='image/bmp')

@app.route('/image/original.bmp', methods=['GET'])
def serve_orig_image():
    global current_orig_image
    if current_orig_image:
        return send_file(BytesIO(current_orig_image.getvalue()), mimetype='image/bmp') 
    else:        
        return send_file(get_no_image(), mimetype='image/bmp')

@app.route('/image/original1.bmp', methods=['GET'])
def serve_orig_image1():
    global current_orig_image
    if current_orig_image:
        return send_file(BytesIO(current_orig_image.getvalue()), mimetype='image/bmp') 
    else:        
        return send_file(get_no_image(), mimetype='image/bmp')

@app.route('/test/adapted_image.bmp', methods=['GET'])
def test_adapted_image():
    global current_send_image
    # Generate the adapted image
    current_send_image = get_and_modify_image()
    # Log the request with timestamp and context
    add_log_entry('Request received at /test/adapted_image', f'serving adapted image for IP: {request.remote_addr}')
    return send_file(BytesIO(current_send_image.getvalue()), mimetype='image/bmp')

## api
## initialize last shown image
current_image_url = 'https://' + get_ip_address() + ':83/image/dummy.bmp'
current_image_url_adapted = 'https://' + get_ip_address() + ':83/image/dummy.bmp'

bmp_send_switch = True
@app.route('/api/display', methods=['GET'])
def display():
    headers = request.headers
    # print(headers)

    # Log the request with timestamp and context
    add_log_entry('Request received at /api/display', f'Headers: {dict(headers)}, URL: {request.url}')

    # Example of accessing specific headers
    id = headers.get('ID')
    access_token = headers.get('Access-Token')
    refresh_rate = headers.get('Refresh-Rate')
    battery_voltage = headers.get('Battery-Voltage')
    fw_version = headers.get('FW-Version')
    rssi = headers.get('RSSI')

    if refresh_rate is not None or battery_voltage is not None or rssi is not None:
        # store the values for refresh_rate, battery_voltage, rssi in last_client_data
        last_client_data['refresh_rate'] = int(refresh_rate)
        last_client_data['battery_voltage'] = float(battery_voltage)
        last_client_data['rssi'] = int(rssi)
        last_client_data['last_contact'] = time.time()

        add_client_data_entry(float(battery_voltage), int(rssi))

    # Respond with a JSON containing status and url
    # Determine the image URL based on the current request count
    global bmp_send_switch
    global current_image_url
    global current_image_url_adapted
    if bmp_send_switch:
        current_image_url = "https://" + get_ip_address() + ":83/image/original.bmp"
        current_image_url_adapted = "https://" + get_ip_address() + ":83/image/screen.bmp"
        bmp_send_switch = False
    else:
        current_image_url =  "https://" + get_ip_address() + ":83/image/original1.bmp"
        current_image_url_adapted = "https://" + get_ip_address() + ":83/image/screen1.bmp"
        bmp_send_switch = True
    
    response = {
        "status": 0,
        "image_url": current_image_url_adapted,
        "update_firmware": False,
        "firmware_url": "https://" + server_ip + ":83/fw/update",
        "refresh_rate": config_refresh_time,
        "reset_firmware": False,
        "special_function": ""
    }
    # generate the footer image as a in memory image as time of requested at client if configured
    global current_orig_image
    global current_send_image
    global config_image_path
    
    with open(config_image_path, 'rb') as f:
        current_orig_image = BytesIO(f.read())
    
    if config_image_modification:
        current_send_image = get_and_modify_image()
    else:
        current_send_image = current_orig_image
    
    add_log_entry('send json /api/display', f'response: {response}')
    return jsonify(response)

@app.route('/api/log', methods=['POST'])
def api_log():
    content = request.json
    logs_array = content.get('log').get('logs_array')
    if logs_array:
        for log_entry in logs_array:
            add_client_log_entry(log_entry)
            print(log_entry)

    # Log the request with timestamp and context
    add_log_entry('Request received at /api/log', f'Content: {content}')

    return jsonify({"status": "logged"}), 200

@app.route('/settings', methods=['GET'])
def get_settings():
    # get the current path to BMP file
    global config_image_path
    # get the current refresh rate
    global last_client_data
    return jsonify({
        'config_image_path': config_image_path,
        'config_refresh_time': config_refresh_time,
        'config_manipulate_image': config_image_modification
    })

@app.route('/settings/refreshtime', methods=['POST'])
def update_refresh_time():
    data = request.json
    new_refresh_time = data.get('refresh_rate')
    
    if new_refresh_time is not None:
        global config_refresh_time
        config_refresh_time = int(new_refresh_time)
        
        # Update the config.yaml file
        config['refresh_time'] = config_refresh_time
        with open(config_file, 'w') as f:
            yaml.safe_dump(config, f)
        
        return jsonify({"status": "success", "new_refresh_time": config_refresh_time}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid refresh rate"}), 400
    
@app.route('/settings/image_modification', methods=['POST'])
def update_image_modification():
    data = request.json
    image_modification = data.get('image_modification')
    
    if image_modification is not None:
        global config_image_modification
        config_image_modification = image_modification
        
        # Update the config.yaml file
        config['image_modification'] = image_modification
        with open(config_file, 'w') as f:
            yaml.safe_dump(config, f)
        
        return jsonify({"status": "success", "image_modification": config_image_modification}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid image_modification"}), 400

@app.route('/settings/imagepath', methods=['POST'])
def update_image_path():
    data = request.json
    new_image_path = data.get('bmp_path')
    
    if new_image_path is not None:
        global config_image_path
        config_image_path = new_image_path
        
        # Update the config.yaml file
        config['image_path'] = config_image_path
        with open(config_file, 'w') as f:
            yaml.safe_dump(config, f)
        
        return jsonify({"status": "success", "new_image_path": config_image_path}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid image path"}), 400


@app.route('/server/log', methods=['GET'])
def log_view():
    # Get the last 30 lines from the log file
    last_30_lines = get_last_n_lines_from_log(log_file, log_show_last_lines)
    # Format logs as plain text
    formatted_logs = "\n".join(last_30_lines)
    return formatted_logs, 200, {'Content-Type': 'text/plain'}

@app.route('/server/battery', methods=['GET'])
def battery_view():
    client_data_db_read = reading_client_data()
    # Format logs as plain text
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    if request.args.get('all') != None:
        response_data = [
            {
                'timestamp': entry['timestamp'],
                'battery_voltage': entry['battery_voltage'],
                'rssi': entry['rssi']
            } for entry in client_data_db_read
        ]
    elif request.args.get('from') != None and request.args.get('to') != None:
        
        from_timestamp = request.args.get('from')
        to_timestamp = request.args.get('to')
        if from_timestamp and to_timestamp:
            response_data = [
            {
                'timestamp': entry['timestamp'],
                'battery_voltage': entry['battery_voltage'],
                'rssi': entry['rssi']
            } for entry in client_data_db_read if from_timestamp <= entry['timestamp'] <= to_timestamp
            ]
    else:
        response_data = [
            {
                'timestamp': entry['timestamp'],
                'battery_voltage': entry['battery_voltage'],
                'rssi': entry['rssi']
            } for entry in client_data_db_read if entry['timestamp'].startswith(today)
        ]
    return jsonify(response_data), 200

@app.route('/status', methods=['GET'])
def get_status():
    uptime_seconds = time.time() - start_time
    uptime_timedelta = timedelta(seconds=uptime_seconds)
    uptime_str = str(uptime_timedelta).split('.')[0]  # Remove microseconds
    cpu_load = psutil.cpu_percent(interval=1)
    current_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    global last_client_data
    global client_data_db
    # client date are not available use last stored data from file
    if last_client_data['last_contact'] == 0:
        client_data_db_read = reading_client_data()
        last_client_data['battery_voltage'] = client_data_db_read[-1]['battery_voltage']
        last_client_data['rssi'] = client_data_db_read[-1]['rssi']
        last_client_data['last_contact'] = client_data_db_read[-1]['timestamp']
        
    global current_image_url

    return jsonify({
        'server': {
            'uptime': uptime_str,
            'cpu_load': round(cpu_load, 1),
            'current_time': current_time
        },
        'client': {
            'battery_voltage': round(last_client_data['battery_voltage'], 2),
            'battery_voltage_max': battery_max_voltage,
            'battery_voltage_min': battery_min_voltage,
            'battery_state': getBatteryState(last_client_data['battery_voltage']),
            'wifi_signal': last_client_data['rssi'],
            'wifi_signal_strength': getWifiSignalStrength(last_client_data['rssi']),
            'refresh_time': last_client_data['refresh_rate'],
            'last_contact': last_client_data['last_contact'],
            'current_image_url': current_image_url,
            'current_image_url_adapted': current_image_url_adapted
        },
        'client_data_db': [
            { 'battery_voltage': entry['battery_voltage'], 'rssi': entry['rssi'], 'timestamp': entry['timestamp'] } for entry in client_data_db
        ]
    })

## web pages

@app.route('/', methods=['GET'])
def main_page():
    return render_template_string(open('web/index.html').read())

@app.route('/image/dummy.bmp', methods=['GET'])
def dummy_image():
    return send_file('web/dummy.bmp', mimetype='image/bmp')


def handle_exit(signum, frame):
    print("Signal received, persisting logs and client data...")
    persist_log()
    persist_client_data()
    persist_client_log_data()
    print("Data persisted. Exiting...")
    exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

if __name__ == '__main__':
    bmp_send_switch = True
    # Generate a self-signed certificate and key
    cert_file = os.path.join(current_dir, 'ssl/cert.pem')
    key_file = os.path.join(current_dir, 'ssl/key.pem')

    if not os.path.exists(cert_file) or not key_file:
        os.system(f'openssl req -x509 -newkey rsa:4096 -keyout {key_file} -out {cert_file} -days 1 -nodes -subj "/CN=localhost"')

    # Run HTTPS server on port 83
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    app.run(host='0.0.0.0', port=83, ssl_context=context)