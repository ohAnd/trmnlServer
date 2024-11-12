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

app = Flask(__name__)
start_time = time.time()
current_dir = os.path.dirname(os.path.abspath(__file__))

## persistance

# List to store logs
logs = [] 
log_persistence_interval = 20  # Number of entries before persisting to file
log_show_last_lines = 20
log_file = os.path.join(current_dir, 'logs/server.log')
db_file = os.path.join(current_dir, 'db/clientData.txt')

client_data = {
    'refresh_rate': 900,
    'battery_voltage': 4.76,
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
    # sort data in client_data_db by timestamp
    client_data_db_read = sorted(client_data_db_read, key=lambda x: x['timestamp'])
    return client_data_db_read

## configuration
# get the config file at current_dir/config.yaml
config_file = os.path.join(current_dir, 'config.yaml')
if os.path.exists(config_file):
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
        config_image_path = config['image_path']
        config_refresh_time = config['refresh_time']
else:
    config = {
        'image_path': 'images/screen.bmp',
        'refresh_time': 900
    }
    with open(config_file, 'w') as f:
        yaml.safe_dump(config, f)
    config_image_path = config['image_path']
    config_refresh_time = config['refresh_time']

## web server
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

server_ip = get_ip_address()
print(f"Server is running on IP: {server_ip}")

## specific BMP serving
bmp_send_switch = True
@app.route('/image/screen.bmp', methods=['GET'])
def serve_image_screen():
    global config_image_path
    # Log the request with timestamp and context
    add_log_entry('Request received at /image/screen.bmp', f'serving image from {config_image_path}')
    return send_file(config_image_path, mimetype='image/bmp')

@app.route('/image/screen1.bmp', methods=['GET'])
def serve_image_screen1():
    global config_image_path
    # Log the request with timestamp and context
    add_log_entry('Request received at /image/screen1.bmp', f'serving image from {config_image_path}')
    return send_file(config_image_path, mimetype='image/bmp')

## api

@app.route('/api/display', methods=['GET'])
def display():
    headers = request.headers
    print(headers)

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
        # store the values for refresh_rate, battery_voltage, rssi in client_data
        client_data['refresh_rate'] = int(refresh_rate)
        client_data['battery_voltage'] = float(battery_voltage)
        client_data['rssi'] = int(rssi)
        client_data['last_contact'] = time.time()

        add_client_data_entry(float(battery_voltage), int(rssi))

    # Respond with a JSON containing status and url
    # Determine the image URL based on the current request count
    global bmp_send_switch
    server_ip = get_ip_address()
    if bmp_send_switch:
        image_url = "https://" + server_ip + ":83/image/screen.bmp"
        bmp_send_switch = False
    else:
        image_url = "https://" + server_ip + ":83/image/screen1.bmp"
        bmp_send_switch = True
    
    response = {
        "status": 0,
        "image_url": image_url,
        "update_firmware": False,
        "firmware_url": "https://" + server_ip + ":83/fw/update",
        "refresh_rate": config_refresh_time,
        "reset_firmware": False,
        "special_function": ""
    }
    add_log_entry('send json /api/display', f'response: {response}')
    return jsonify(response)

@app.route('/api/log', methods=['POST'])
def api_log():
    content = request.json
    print(content)

    # Log the request with timestamp and context
    add_log_entry('Request received at /api/log', f'Content: {content}')

    return jsonify({"status": "logged"}), 200

@app.route('/settings', methods=['GET'])
def get_settings():
    # get the current path to BMP file
    global config_image_path
    # get the current refresh rate
    global client_data
    return jsonify({
        'config_image_path': config_image_path,
        'config_refresh_time': config_refresh_time
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
    global client_data
    global client_data_db
    # client date are not available use last stored data from file
    if client_data['last_contact'] == 0:
        client_data_db_read = reading_client_data()
        client_data['battery_voltage'] = client_data_db_read[-1]['battery_voltage']
        client_data['rssi'] = client_data_db_read[-1]['rssi']
        client_data['last_contact'] = client_data_db_read[-1]['timestamp']
    
    return jsonify({
        'server': {
            'uptime': uptime_str,
            'cpu_load': round(cpu_load, 1),
            'current_time': current_time
        },
        'client': {
            'battery_voltage': round(client_data['battery_voltage'], 2),
            'battery_state': round(((float(client_data['battery_voltage']) - 3.3) / (4.76 - 3.3)) * 100, 1),
            'wifi_signal': client_data['rssi'],
            'refresh_time': client_data['refresh_rate'],
            'last_contact': client_data['last_contact']
        },
        'client_data_db': [
            { 'battery_voltage': entry['battery_voltage'], 'rssi': entry['rssi'], 'timestamp': entry['timestamp'] } for entry in client_data_db
        ]
    })

## web pages

@app.route('/', methods=['GET'])
def status_page():
    return render_template_string(open('web/index.html').read())


def handle_exit(signum, frame):
    print("Signal received, persisting logs and client data...")
    persist_log()
    persist_client_data()
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