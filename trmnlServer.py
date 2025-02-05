#! /usr/bin/env python
# %%
import datetime
import ssl
import os
import time
from datetime import timedelta
from collections import deque
import signal
import socket
from io import BytesIO
import yaml
import psutil
from flask import Flask, request, jsonify, render_template_string, send_file
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)
start_time = time.time()

BATTERY_MAX_VOLTAGE = 4.1
BATTERY_MIN_VOLTAGE = 2.3

base_path = os.path.dirname(os.path.abspath(__file__))
# get param to set a specific path for log, db, cert
if len(os.sys.argv) > 1:
    current_dir = os.sys.argv[1]
    if not os.path.exists(current_dir):
        current_dir = base_path
    else:
        # create the ssl folder if not exists
        ssl_folder = os.path.join(current_dir, 'ssl')
        if not os.path.exists(ssl_folder):
            os.makedirs(ssl_folder)
        # create the logs folder if not exists
        logs_folder = os.path.join(current_dir, 'logs')
        if not os.path.exists(logs_folder):
            os.makedirs(logs_folder)
        # create the db folder if not exists
        db_folder = os.path.join(current_dir, 'db')
        if not os.path.exists(db_folder):
            os.makedirs(db_folder)
else:
    current_dir = base_path

###################################################################################################
## persistance
# List to store logs
logs = []
LOG_PERSISTANCE_INTERVAL = 20  # Number of entries before persisting to file
LOG_SHOW_LAST_LINES = 20
log_file = os.path.join(current_dir, 'logs/server.log')
db_file = os.path.join(current_dir, 'db/clientData.txt')
db_client_log_file = os.path.join(current_dir, 'db/clientLog.txt')

last_client_data = {
    'refresh_rate': 900,
    'battery_voltage': BATTERY_MAX_VOLTAGE,
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
    """
    Retrieve the last n lines from the log file and combine them with formatted logs.

    Args:
        file_path (str): The path to the log file.
        n (int): The number of lines to retrieve from the end of the log file.

    Returns:
        list: A list of combined log lines.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
        file_logs = lines[-n:]

    formatted_logs = [f"{log['timestamp']} -- [{log['context']}] -- {log['info']}\n" for log in logs]
    combined_logs = file_logs + formatted_logs
    return combined_logs

def persist_log():
    """
    Persist the logs to the log file and clear the in-memory logs.
    """
    with open(log_file, 'a', encoding='utf-8') as f:
        for log in logs:
            f.write(f"{log['timestamp']} -- [{log['context']}] -- {log['info']}\n")
    logs.clear()

def add_log_entry(log_context, info):
    """
    Add a log entry to the in-memory logs and persist if the interval is reached.

    Args:
        log_context (str): The context of the log entry.
        info (str): The information to log.
    """
    log_entry = {
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'context': log_context,
        'info': info
    }
    logs.append(log_entry)
    if len(logs) >= LOG_PERSISTANCE_INTERVAL:
        persist_log()

def add_client_data_entry(battery_voltage, rssi):
    """
    Add a client data entry to the in-memory database and persist if the interval is reached.

    Args:
        battery_voltage (float): The battery voltage of the client.
        rssi (int): The RSSI (Received Signal Strength Indicator) of the client.
    """
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
    if len(client_data_db) >= LOG_PERSISTANCE_INTERVAL:
        persist_client_data()

def persist_client_data():
    """
    Persist the client data to the database file and clear the in-memory database,
    keeping only the last entry.
    """
    with open(db_file, 'a', encoding='utf-8') as f:
        for entry in client_data_db:
            f.write(
                f"{entry['timestamp']} -- bVolt: {entry['battery_voltage']}, "
                f"rssi: {entry['rssi']}\n"
            )
    if len(client_data_db) > 1:
        last_entry = client_data_db.pop()
        client_data_db.clear()
        client_data_db.append(last_entry)

def add_client_log_entry(log_entry):
    """
    Add a log entry to the client log database and persist if the interval is reached.

    Args:
        log_entry (dict): The log entry to add to the client log database.
    """
    # Append the new entry to the client_log_db
    client_log_db.append(log_entry)
    if len(client_log_db) >= LOG_PERSISTANCE_INTERVAL:
        persist_client_log_data()

def persist_client_log_data():
    """
    Appends the entries from the client_log_db to the specified log file and retains only the last entry in the client_log_db.

    This function opens the log file in append mode and writes each entry from the client_log_db to the file. 
    After writing, if there is more than one entry in the client_log_db, it retains only the last entry and clears the rest.

    Args:
        None

    Returns:
        None
    """
    with open(db_client_log_file, 'a', encoding='utf-8') as f:
        for entry in client_log_db:
            f.write(f"{entry}\n")
    if len(client_log_db) > 1:
        last_entry = client_log_db.pop()
        client_log_db.clear()
        client_log_db.append(last_entry)

def reading_client_data():
    """
    Read client data from the file and combine it with in-memory data.

    Returns:
        list: A list of client data entries sorted by timestamp.
    """
    client_data_db_read = []
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
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

###################################################################################################
## configuration
# get the config file at current_dir/config.yaml
config_file = os.path.join(current_dir, 'config.yaml')
if os.path.exists(config_file):
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
        config_image_path = config['image_path']
        config_image_modification = config['image_modification']
        config_refresh_time = config['refresh_time']
        BATTERY_MAX_VOLTAGE = config['battery_max_voltage']
        BATTERY_MIN_VOLTAGE = config['battery_min_voltage']
else:
    config = {
        'image_path': 'images/screen.bmp',
        'image_modification': True,        
        'refresh_time': 900,
        'battery_max_voltage': 4.1,
        'battery_min_voltage': 2.3
    }
    with open(config_file, 'w', encoding='utf-8') as f:
        yaml.safe_dump(config, f)
    print("Config file not found. Created a new one with default values.")
    print("Please restart the server after configuring the settings in config.yaml")
    exit(0)

###################################################################################################
## bmp modification
# In-memory object to store the last sent image as a blob
current_orig_image = None
current_send_image = None

def getBatteryIcon(battery):
    """
    Returns a battery icon based on the battery percentage.

    Args:
        battery (int): The battery percentage.

    Returns:
        str: A string representing the battery icon.
    """
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
    """
    Adds a footer to an image with WiFi and battery percentages, and the current date and time.

    Args:
        src_image (str): Path to the source image file.
        wifi_percentage (float): WiFi signal strength percentage.
        battery_percentage (float): Battery charge percentage.

    Returns:
        BytesIO: A BytesIO object containing the new image with the footer in BMP format.
    """
    # Load the source image
    img = Image.open(src_image)
    footer_height = 35
    # Resize the source image to make space for the footer
    img = img.crop((0, 0, img.width, img.height - footer_height))

    # define appearance
    background = 1 # white - 1 black
    # Create a new image with extra space for the footer
    # '1' mode for 1-bit pixels, black and white
    new_img = Image.new('1', (img.width, img.height + footer_height), color=1 - background)

    # Paste the original image onto the new image
    new_img.paste(img, (0, 0))

    # Initialize ImageDraw
    d = ImageDraw.Draw(new_img)

    # Load fonts
    try:
        icon_font = ImageFont.truetype("web/fontawesome-webfont.ttf", 24)
        # text_font = ImageFont.truetype("DejaVuSans.ttf", 14)
        text_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 14)
    except IOError:
        icon_font = ImageFont.load_default()
        text_font = ImageFont.load_default()

    # Define positions
    text_line_height = 7
    symbol_line_height = 4
    wifi_icon_position = (18, img.height + symbol_line_height)
    wifi_text_position = (50, img.height + text_line_height)
    battery_icon_position = (104, img.height + symbol_line_height)
    battery_text_position = (140, img.height + text_line_height)
    date_time_position = (img.width - 155, img.height + text_line_height)

    # draw line if backgorund = white
    if background == 0:
        d.line([(0, img.height + 1), (img.width, img.height + 1)], fill=0, width=2)
    else:
        width_left_side = 142
        if battery_percentage == 255:
            width_left_side = 100            
        # draw white rounded rectangle for left and right side
        d.rounded_rectangle(
           [-10, img.height + 3, wifi_text_position[0] + width_left_side, img.height + footer_height + 5],
            fill=1,
            radius=5
        )
        d.rounded_rectangle(
            [date_time_position[0] - 8, img.height + 3, 810, img.height + footer_height + 5],
            fill=1,
            radius=5
        )
        background = 0


    # Draw WiFi icon and percentage
    wifi_icon = "\uf1eb"
    d.text(wifi_icon_position,
           wifi_icon, fill=background, font=icon_font
    )  # fill=1 for white
    d.text(wifi_text_position,
           f"{round(wifi_percentage)} %", fill=background, font=text_font
    )  # fill=1 for white

    # Draw battery icon and percentage
    battery_icon = getBatteryIcon(battery_percentage)

    if battery_percentage == 255:
        d.text(
            battery_icon_position,
            "\uf244",
            fill=background,
            font=icon_font
        )  # fill=1 for white
        d.text(
            (battery_icon_position[0] + 10,
             battery_icon_position[1]),
            "\uf0e7", fill=background,
            font=icon_font
        )  # fill=1 for white
    else:
        d.text(
            battery_icon_position,
            battery_icon,
            fill=background,
            font=icon_font
        )  # fill=1 for white
        d.text(
            battery_text_position,
            f"{round(battery_percentage)} %",
            fill=background,
            font=text_font
        )  # fill=1 for white

    # Draw date and time
    date_time = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    d.text(date_time_position, date_time, fill=background, font=text_font)  # fill=1 for white

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
    """
    Retrieves and modifies an image by adding a footer with WiFi signal strength and battery percentage.

    This function uses global variables and other helper functions to get the WiFi signal strength and battery state
    from the last client data, and then adds this information as a footer to the image specified by the global 
    config_image_path.

    Returns:
        Image: The modified image with the added footer.
    """
    global config_image_path
    # Example usage
    wifi_percentage = getWifiSignalStrength(last_client_data['rssi'])
    battery_percentage = getBatteryState(last_client_data['battery_voltage'])
    return add_footer_to_image(config_image_path,wifi_percentage, battery_percentage)

def get_no_image():
    """
    Create a blank image with a white background and overlay text indicating no image is available,
    along with the current date and time. The image is saved in BMP format and returned as a BytesIO object.

    Returns:
        BytesIO: A BytesIO object containing the generated image in BMP format.
    """
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
###################################################################################################
## helper
def get_ip_address():
    """
    Get the local IP address of the machine.

    This function creates a UDP socket and connects to a remote address to 
    determine the local IP address. The remote address does not need to be 
    reachable. If an error occurs, it defaults to '127.0.0.1'.

    Returns:
        str: The local IP address of the machine.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
    except (IndexError, KeyError):
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

# get the ip address of the server after startup of script
server_ip = get_ip_address()
print(f"Server is running on IP: {server_ip}")

# calculate battery state
def getBatteryState(battery_voltage):
    """
    Calculate the battery state based on the given battery voltage.

    Args:
        battery_voltage (float or str): The voltage of the battery.

    Returns:
        int or float: The battery state as a percentage (0-100) or 255 if the battery is charging.

    Notes:
        - If the battery voltage is greater than 4.6, the battery is considered to be charging and the function returns 255.
        - The battery state is calculated as a percentage based on the minimum and maximum battery voltages defined by BATTERY_MIN_VOLTAGE and BATTERY_MAX_VOLTAGE.
        - The battery state is rounded to one decimal place.
        - The battery state is capped between 0 and 100.
    """
    if float(battery_voltage) > 4.6: # is chharging
        return 255
    battery_state = round(
        (
            (float(battery_voltage) - BATTERY_MIN_VOLTAGE) /
            (BATTERY_MAX_VOLTAGE - BATTERY_MIN_VOLTAGE)) * 100, 1
        )
    if battery_state > 100:
        battery_state = 100
    elif battery_state < 0:
        battery_state = 0
    return battery_state

# calculate wifi signal strength
def getWifiSignalStrength(rssi):
    """
    Calculate the WiFi signal strength quality based on the RSSI value.

    The RSSI (Received Signal Strength Indicator) value is used to determine the quality of the WiFi signal.
    The quality is calculated as follows:
    - If RSSI is less than or equal to -100, the quality is 0 (poor signal).
    - If RSSI is greater than or equal to -50, the quality is 100 (excellent signal).
    - Otherwise, the quality is calculated using the formula: 2 * (rssi + 100).

    Args:
        rssi (int): The RSSI value of the WiFi signal.

    Returns:
        int: The calculated WiFi signal strength quality as a percentage.
    """
    if rssi <= -100:
        quality = 0
    elif rssi >= -50:
        quality = 100
    else:
        quality = 2 * (rssi + 100)
    return quality

###################################################################################################
## web server
## specific BMP serving

@app.route('/image/screen.bmp', methods=['GET'])
def serve_image_screen():
    """
    Serve the current image as a BMP file.

    This function logs the request with a timestamp and the client's IP address,
    then returns the current image in BMP format.

    Returns:
        Response: A Flask response object containing the image file.
    """
    global current_send_image
    # Log the request with timestamp and context
    add_log_entry(
        'Request received at /image/screen.bmp',
        f'serving image for IP: {request.remote_addr}'
    )
    return send_file(BytesIO(current_send_image.getvalue()), mimetype='image/bmp')

@app.route('/image/screen1.bmp', methods=['GET'])
def serve_image_screen1():
    """
    Serve the current image for screen1.bmp.

    This function logs the request with a timestamp and context, then serves the 
    current image stored in `current_send_image` as a BMP file.

    Returns:
        Response: A Flask response object containing the image data with a 
        'image/bmp' MIME type.
    """
    global current_send_image
    # Log the request with timestamp and context
    add_log_entry(
        'Request received at /image/screen1.bmp',
        f'serving image for IP: {request.remote_addr}'
    )
    return send_file(BytesIO(current_send_image.getvalue()), mimetype='image/bmp')

@app.route('/image/original.bmp', methods=['GET'])
def serve_orig_image():
    """
    Serve the original image if available, otherwise serve a placeholder image.

    This function checks if the global variable `current_orig_image` is set. If it is,
    the function returns the image as a BMP file. If `current_orig_image` is not set,
    it returns a placeholder image as a BMP file.

    Returns:
        Response: A Flask response object containing the image file.
    """
    global current_orig_image
    if current_orig_image:
        return send_file(BytesIO(current_orig_image.getvalue()), mimetype='image/bmp')
    else:
        return send_file(get_no_image(), mimetype='image/bmp')

@app.route('/image/original1.bmp', methods=['GET'])
def serve_orig_image1():
    """
    Serve the original image if available, otherwise serve a default 'no image' placeholder.

    Returns:
        Response: A Flask response object containing the image data with 'image/bmp' MIME type.
    """
    global current_orig_image
    if current_orig_image:
        return send_file(BytesIO(current_orig_image.getvalue()), mimetype='image/bmp')
    else:
        return send_file(get_no_image(), mimetype='image/bmp')

@app.route('/test/adapted_image.bmp', methods=['GET'])
def test_adapted_image():
    """
    Handles the request to generate and serve an adapted image.

    This function performs the following steps:
    1. Generates the adapted image by calling `get_and_modify_image()`.
    2. Logs the request with a timestamp and the client's IP address.
    3. Returns the adapted image as a BMP file.

    Returns:
        Response: A Flask response object containing the adapted image in BMP format.
    """
    global current_send_image
    # Generate the adapted image
    current_send_image = get_and_modify_image()
    # Log the request with timestamp and context
    add_log_entry(
        'Request received at /test/adapted_image',
        f'serving adapted image for IP: {request.remote_addr}'
    )
    return send_file(BytesIO(current_send_image.getvalue()), mimetype='image/bmp')

## api
## initialize last shown image
current_image_url = 'https://' + get_ip_address() + ':83/image/dummy.bmp'
current_image_url_adapted = 'https://' + get_ip_address() + ':83/image/dummy.bmp'

bmp_send_switch = True
@app.route('/api/display', methods=['GET'])
def display():
    """
    Handle the /api/display endpoint.

    This function processes the incoming request, logs the request details, extracts specific headers,
    updates client data, determines the image URL to respond with, and constructs a JSON response.

    Headers:
        ID (str): The client ID.
        Access-Token (str): The access token.
        Refresh-Rate (str): The refresh rate.
        Battery-Voltage (str): The battery voltage.
        FW-Version (str): The firmware version.
        RSSI (str): The RSSI value.

    Returns:
        Response: A JSON response containing status, image URL, firmware update URL, refresh rate, and other details.
    """
    headers = request.headers
    # print(headers)

    # Log the request with timestamp and context
    add_log_entry(
        'Request received at /api/display',
        f'Headers: {dict(headers)},URL: {request.url}'
    )

    # Example of accessing specific headers
    client_id = headers.get('ID')
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
    """
    Handles the /api/log endpoint to log client data.

    This function processes a JSON request containing log entries, 
    adds each log entry to the client log, and prints it. Additionally, 
    it logs the request with a timestamp and context.

    Returns:
        Response: A JSON response with a status message and HTTP status code 200.
    """
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
    """
    Retrieve the current settings for the terminal server.

    This function returns a JSON response containing the current configuration
    settings, including the path to the BMP file, the refresh rate, and the 
    image manipulation settings.

    Returns:
        Response: A Flask JSON response object containing the following keys:
            - config_image_path (str): The current path to the BMP file.
            - config_refresh_time (int): The current refresh rate.
            - config_manipulate_image (bool): The current image manipulation setting.
    """
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
    """
    Update the refresh time in the configuration.

    This function reads the new refresh time from the JSON payload of the request,
    updates the global configuration variable `config_refresh_time`, and writes
    the updated configuration back to the `config.yaml` file.

    Returns:
        Response: A JSON response indicating success or failure.
            - On success: {"status": "success", "new_refresh_time": <new_refresh_time>}, HTTP status code 200.
            - On failure: {"status": "error", "message": "Invalid refresh rate"}, HTTP status code 400.
    """
    data = request.json
    new_refresh_time = data.get('refresh_rate')

    if new_refresh_time is not None:
        global config_refresh_time
        config_refresh_time = int(new_refresh_time)

        # Update the config.yaml file
        config['refresh_time'] = config_refresh_time
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.safe_dump(config, f)

        return jsonify({"status": "success", "new_refresh_time": config_refresh_time}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid refresh rate"}), 400

@app.route('/settings/image_modification', methods=['POST'])
def update_image_modification():
    """
    Update the image modification configuration.

    This function retrieves the 'image_modification' value from the JSON payload
    of the incoming request. If the value is present, it updates the global
    configuration and writes the new configuration to the 'config.yaml' file.
    It then returns a success response with the updated 'image_modification' value.
    If the value is not present, it returns an error response.

    Returns:
        Response: A JSON response indicating the status of the update operation.
                  - On success: {"status": "success", "image_modification": <updated_value>}, HTTP status code 200.
                  - On error: {"status": "error", "message": "Invalid image_modification"}, HTTP status code 400.
    """
    data = request.json
    image_modification = data.get('image_modification')

    if image_modification is not None:
        global config_image_modification
        config_image_modification = image_modification

        # Update the config.yaml file
        config['image_modification'] = image_modification
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.safe_dump(config, f)

        return jsonify({"status": "success", "image_modification": config_image_modification}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid image_modification"}), 400

@app.route('/settings/imagepath', methods=['POST'])
def update_image_path():
    """
    Updates the image path in the configuration file based on the JSON payload from the request.

    The function expects a JSON payload with a key 'bmp_path'. If the key is present and the value is not None,
    it updates the global `config_image_path` variable and the `image_path` entry in the `config.yaml` file.

    Returns:
        Response: A JSON response with status "success" and the new image path if the update is successful.
                  A JSON response with status "error" and an error message if the image path is invalid.
    """
    data = request.json
    new_image_path = data.get('bmp_path')

    if new_image_path is not None:
        global config_image_path
        config_image_path = new_image_path

        # Update the config.yaml file
        config['image_path'] = config_image_path
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.safe_dump(config, f)

        return jsonify({"status": "success", "new_image_path": config_image_path}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid image path"}), 400


@app.route('/server/log', methods=['GET'])
def log_view():
    """
    Retrieve and format the last 30 lines from the log file.

    This function reads the last 30 lines from the specified log file,
    formats them as plain text, and returns the formatted logs along
    with an HTTP status code and content type.

    Returns:
        tuple: A tuple containing the formatted log lines as a string,
               an HTTP status code (200), and a dictionary with the
               content type set to 'text/plain'.
    """
    # Get the last 30 lines from the log file
    last_30_lines = get_last_n_lines_from_log(log_file, LOG_SHOW_LAST_LINES)
    # Format logs as plain text
    formatted_logs = "\n".join(last_30_lines)
    return formatted_logs, 200, {'Content-Type': 'text/plain'}

@app.route('/server/battery', methods=['GET'])
def battery_view():
    """
    Fetches battery data from the client database and returns it in JSON format.

    The function supports three types of queries:
    1. If the 'all' query parameter is provided, it returns all entries.
    2. If the 'from' and 'to' query parameters are provided, it returns entries within the specified timestamp range.
    3. If no query parameters are provided, it returns entries for the current day.

    Returns:
        tuple: A tuple containing the JSON response data and the HTTP status code 200.
    """
    client_data_db_read = reading_client_data()
    # Format logs as plain text
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    response_data = []
    if request.args.get('all') is not None:
        response_data = [
            {
                'timestamp': entry['timestamp'],
                'battery_voltage': entry['battery_voltage'],
                'rssi': entry['rssi']
            } for entry in client_data_db_read
        ]
    elif request.args.get('from') is not None and request.args.get('to') is not None:

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
    """
    Retrieve the current status of the server and client.

    This function gathers various metrics about the server's uptime, CPU load, 
    and current time. It also retrieves client data, including battery voltage, 
    WiFi signal strength, and the last contact timestamp. If the client data is 
    not available, it reads the last stored data from a file.

    Returns:
        Response: A JSON response containing the server and client status, 
                  including:
                  - server uptime
                  - CPU load
                  - current time
                  - client battery voltage
                  - client WiFi signal strength
                  - client refresh time
                  - client last contact timestamp
                  - current image URL
                  - historical client data from the database
    """
    uptime_seconds = time.time() - start_time
    uptime_timedelta = timedelta(seconds=uptime_seconds)
    uptime_str = str(uptime_timedelta).split('.', maxsplit=1)[0]  # Remove microseconds
    cpu_load = psutil.cpu_percent(interval=1)
    current_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    global last_client_data
    global client_data_db
    # client date are not available use last stored data from file
    if last_client_data['last_contact'] == 0:
        client_data_db_read = reading_client_data()
        try:
            last_client_data['battery_voltage'] = client_data_db_read[-1]['battery_voltage']
            last_client_data['rssi'] = client_data_db_read[-1]['rssi']
            last_client_data['last_contact'] = client_data_db_read[-1]['timestamp']
        except (IndexError, KeyError):
            last_client_data['battery_voltage'] = 0
            last_client_data['rssi'] = 0
            last_client_data['last_contact'] = 1735686000

    global current_image_url

    return jsonify({
        'server': {
            'uptime': uptime_str,
            'cpu_load': round(cpu_load, 1),
            'current_time': current_time
        },
        'client': {
            'battery_voltage': round(last_client_data['battery_voltage'], 2),
            'battery_voltage_max': BATTERY_MAX_VOLTAGE,
            'battery_voltage_min': BATTERY_MIN_VOLTAGE,
            'battery_state': getBatteryState(last_client_data['battery_voltage']),
            'wifi_signal': last_client_data['rssi'],
            'wifi_signal_strength': getWifiSignalStrength(last_client_data['rssi']),
            'refresh_time': last_client_data['refresh_rate'],
            'last_contact': last_client_data['last_contact'],
            'current_image_url': current_image_url,
            'current_image_url_adapted': current_image_url_adapted
        },
        'client_data_db': [
            { 
                'battery_voltage': entry['battery_voltage'],
                'rssi': entry['rssi'],
                'timestamp': entry['timestamp']
            } for entry in client_data_db
        ]
    })

## web pages

@app.route('/', methods=['GET'])
def main_page():
    """
    Renders the main page of the web application.

    This function reads the content of the 'index.html' file located in the 'web' directory
    and returns it as a rendered template string.

    Returns:
        str: The rendered HTML content of the main page.
    """
    with open('web/index.html', 'r', encoding='utf-8') as f:
        return render_template_string(f.read())

@app.route('/image/dummy.bmp', methods=['GET'])
def dummy_image():
    """
    Sends a dummy BMP image file to the client.

    Returns:
        Response: A Flask response object containing the dummy BMP image file.
    """
    return send_file('web/dummy.bmp', mimetype='image/bmp')


def handle_exit(signum, frame):
    """
    Handle the exit signal and persist necessary data before exiting.

    This function is triggered when a termination signal is received. It ensures
    that logs and client data are persisted before the program exits.

    Args:
        signum (int): The signal number received.
        frame (FrameType): The current stack frame (or None).

    Returns:
        None
    """
    print("Signal received, persisting logs and client data...")
    persist_log()
    persist_client_data()
    persist_client_log_data()
    print("Data persisted. Exiting...")
    exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

from werkzeug.serving import WSGIRequestHandler

class SSLRequestHandler(WSGIRequestHandler):
    """
    SSLRequestHandler is a custom request handler that extends WSGIRequestHandler
    to handle SSL-specific errors gracefully.

    Methods:
        handle():
            Overrides the handle method to catch and ignore SSL protocol shutdown errors.
            If any other SSL error occurs, it re-raises the exception.
    """
    def handle(self):
        try:
            super().handle()
        except ssl.SSLError as e:
            if e.reason == 'PROTOCOL_IS_SHUTDOWN':
                pass  # Ignore SSL protocol shutdown errors
            else:
                raise

if __name__ == '__main__':
    WSGIRequestHandler = SSLRequestHandler
    bmp_send_switch = True
    # Generate a self-signed certificate and key
    cert_file = os.path.join(current_dir, 'ssl/cert.pem')
    key_file = os.path.join(current_dir, 'ssl/key.pem')

    if not os.path.exists(cert_file) or not key_file:
        os.system(
            f'openssl req -x509 -newkey rsa:4096 -keyout {key_file} -out {cert_file} '
            f'-days 1 -nodes -subj "/CN=localhost"'
        )

    # Run HTTPS server on port 83
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    app.run(host='0.0.0.0', port=1184, ssl_context=context)
# %%
