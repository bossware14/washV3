from wifi_manager import WifiManager
import machine
import time
import ujson
import ubinascii
import network
import struct
import ujson as json
import os
import requests
from umqtt.simple import MQTTClient

# --- ส่วนโค้ดเดิมที่ไม่ต้องแก้ไข (จาก main.py เดิม) ---
def resetWIFI():
    coder_version = {"version":2}
    f = open('version.json','w')
    f.write(json.dumps(coder_version))
    f.close()
    if check_file_exists('wifi.dat') :
        os.remove('wifi.dat')
    if check_file_exists('config.json') :
        os.remove('config.json')


def read_credentials(selffle):
    lines = []
    try:
        with open(selffle) as file:
            lines = file.readlines()
    except Exception as error:
        if selffle:
            print(error)
        pass
    profiles = {}
    for line in lines:
        ssid, password = line.strip().split(';')
        profiles['ssid'] = ssid
        profiles['password'] = password
    return profiles

def check_file_exists(filename):
    try:
        os.stat(filename)
        return True
    except OSError:
        return False

def get_device_serial_number():
    try:
        import machine
        import ubinascii
        return ubinascii.hexlify(machine.unique_id()).decode('utf-8').upper()
    except :
        return "UNKNOWN_SERIAL"

# MQTT Settings
MQTT_BROKER = "34.124.162.209"
MQTT_PORT = 1883
MQTT_CLIENT_ID = get_device_serial_number()
STATUS_TOPIC = b"washing_machine/" + MQTT_CLIENT_ID + b"/status"
COMMAND_TOPIC = b"washing_machine/" + MQTT_CLIENT_ID + b"/commands"

led = machine.Pin(2, machine.Pin.OUT, value=0)
debounce_delay = 1000
timer_direction = 0

import wash

# Global MQTT client instance
client = None

def sub_cb(topic, msg):
    try:
        data_json = json.loads(msg.decode())
        interpret_command(data_json)
    except ValueError:
        print(f"Failed to parse JSON from MQTT message")
    except Exception as e:
        print(f"Error in sub_cb: {e}")

def interpret_command(data_json):
    global client
    command_response_topic = b"washing_machine/" + MQTT_CLIENT_ID + b"/command_response"

    if 'command' in data_json:
        cmd = data_json['command']
        response_data = {}

        try:
            # --- ส่วนที่นำกลับมาและปรับปรุงสำหรับการอัปเดตโค้ด ---
            if cmd['key'] == 'update_code' and 'url' in cmd and 'file_name' in cmd:
                print(f"Updating code from {cmd['url']} to {cmd['file_name']}")
                response_update = requests.get(cmd['url'])
                if response_update.status_code == 200:
                    with open(cmd['file_name'], 'w') as f:
                        f.write(response_update.text)
                    response_data = {"status": "success", "message": f"Updated {cmd['file_name']}. Rebooting..."}
                    client.publish(command_response_topic, json.dumps(response_data).encode())
                    time.sleep(5)
                    machine.reset()
                    return True # ออกจากฟังก์ชันหลังจากสั่งรีเซ็ต
                else:
                    response_data = {"status": "error", "message": f"Failed to download {cmd['file_name']}. Status code: {response_update.status_code}"}

            elif cmd['key'] == 'update_wash' and 'value' in cmd:
                print(f"Updating wash.py from {cmd['value']}")
                response_update = requests.get(cmd['value'])
                if response_update.status_code == 200:
                    with open('wash.py', 'w') as f:
                        f.write(response_update.text)
                    response_data = {"status": "success", "message": "Updated wash.py. Rebooting..."}
                    client.publish(command_response_topic, json.dumps(response_data).encode())
                    time.sleep(5)
                    machine.reset()
                    return True

                else:
                    response_data = {"status": "error", "message": f"Failed to update wash.py. Status code: {response_update.status_code}"}

            elif cmd['key'] == 'update_main' and 'value' in cmd:
                print(f"Updating main.py from {cmd['value']}")
                response_update = requests.get(cmd['value'])
                if response_update.status_code == 200:
                    with open('main.py', 'w') as f:
                        f.write(response_update.text)
                    response_data = {"status": "success", "message": "Updated main.py. Rebooting..."}
                    client.publish(command_response_topic, json.dumps(response_data).encode())
                    time.sleep(5)
                    machine.reset()
                    return True
                else:
                    response_data = {"status": "error", "message": f"Failed to update main.py. Status code: {response_update.status_code}"}

            elif cmd['key'] == 'update_version':
                print("Updating all versions...")
                boot_url = 'https://raw.githubusercontent.com/SuperBoss221/wash_mqtt/refs/heads/main/boot.py'
                main_url = 'https://raw.githubusercontent.com/SuperBoss221/wash_mqtt/refs/heads/main/main.py'
                wifi_url = 'https://raw.githubusercontent.com/SuperBoss221/wash_mqtt/refs/heads/main/wifi_manager.py'
                wash_url = 'https://raw.githubusercontent.com/SuperBoss221/wash_mqtt/refs/heads/main/wash.py'

                update_success = True
                files_updated = []
                
                # ฟังก์ชันช่วยดาวน์โหลดและบันทึกไฟล์
                def download_and_save(url, filename):
                    nonlocal update_success, files_updated
                    try:
                        print(f"Downloading {filename} from {url}")
                        response = requests.get(url)
                        if response.status_code == 200:
                            with open(filename, 'w') as f:
                                f.write(response.text)
                            print(f"Successfully updated {filename}")
                            files_updated.append(filename)
                        else:
                            print(f"Failed to download {filename}: Status {response.status_code}")
                            update_success = False
                        response.close() # ปิดการเชื่อมต่อ
                    except Exception as e:
                        print(f"Error updating {filename}: {e}")
                        update_success = False

                # เริ่มกระบวนการอัปเดตทีละไฟล์
                download_and_save(boot_url, 'boot.py')
                download_and_save(main_url, 'main.py')
                download_and_save(wifi_url, 'wifi_manager.py')
                download_and_save(wash_url, 'wash.py')

                if update_success:
                    response_data = {"status": "success","version": 3.2, "message": f"Firmware update initiated. Updated: {', '.join(files_updated)}. Rebooting..."}
                else:
                    response_data = {"status": "partial_success","version": 3.2, "message": f"Firmware update completed with errors. Updated: {', '.join(files_updated)}. Rebooting..."}
                
                client.publish(command_response_topic, json.dumps(response_data).encode())
                led.value(0)
                time.sleep(5)
                machine.reset()
                return True # ออกจากฟังก์ชันหลังจากสั่งรีเซ็ต
            # --- จบส่วนอัปเดตโค้ด ---

            elif cmd['key'] == 'reset_error':
                txt = wash.reset_error()
                response_data = {"status": "success", "version": 3.2,"message": "Error reset initiated.", "modbus_response": json.loads(txt)}
                client.publish(command_response_topic, json.dumps(response_data).encode())
                led.value(0)
                machine.reset()
                return True
            elif cmd['key'] == 'reset_wifi':
                resetWIFI()
                response_data = {"status": "success", "version": 3.2,"message": "WiFi reset initiated."}
                client.publish(command_response_topic, json.dumps(response_data).encode())
                time.sleep(5)
                led.value(0)
                machine.reset()
                return True
            elif cmd['key'] == 'get_status':
                wash_status = json.loads(wash.get_machine_status())
                status_payload = {"version": 3.2, "cmd": "get_status", "ip": str(WiFIManager.get_address()[0]), "client_id": get_device_serial_number(), "status": wash_status}
                client.publish(STATUS_TOPIC, json.dumps(status_payload).encode())
                response_data = {"status": "success", "version": 3.2,"message": "Status published."}
            elif cmd['key'] == 'menu' and 'value' in cmd:
                txt = wash.select_program(int(cmd['value']))
                response_data = {"status": "success","version": 3.2, "message": f"Program {cmd['value']} selected.", "modbus_response": json.loads(txt)}
            elif cmd['key'] == 'coins' and 'value' in cmd:
                txt = wash.add_coins(int(cmd['value']))
                response_data = {"status": "success", "version": 3.2,"message": f"Added {cmd['value']} coins.", "modbus_response": json.loads(txt)}
            elif cmd['key'] == 'start':
                txt = wash.start_operation()
                response_data = {"status": "success", "version": 3.2,"message": "Start command sent.", "modbus_response": json.loads(txt)}
            elif cmd['key'] == 'stop':
                txt = wash.stop_operation()
                response_data = {"status": "success", "message": "Stop command sent.", "modbus_response": json.loads(txt)}
            elif cmd['key'] == 'command' and 'address' in cmd and 'value' in cmd:
                txt = wash.sendcommand(int(cmd['address']), int(cmd['value']))
                response_data = {"status": "success", "version": 3.2,"message": "Custom command sent.", "modbus_response": json.loads(txt)}
            elif cmd['key'] == 'reboot':
                response_data = {"status": "success","version": 3.2, "message": "Device rebooting."}
                client.publish(command_response_topic, json.dumps(response_data).encode())
                time.sleep(5)
                machine.reset()
            else:
                response_data = {"status": "error", "version": 3.2,"message": "Unknown or incomplete command."}

        except Exception as e:
            print(f"Error processing command: {e}")
            response_data = {"status": "error","version": 3.2, "message": f"Error processing command: {e}"}
        finally:
            client.publish(command_response_topic, json.dumps(response_data).encode())


# --- ส่วนการเชื่อมต่อและกู้คืน (Robust Connection & Recovery) ---

def connect_and_subscribe():
    global client
    if client:
        try:
            client.disconnect()
            print("Disconnected existing MQTT client.")
        except Exception as e:
            print(f"Error disconnecting old client: {e}")

    try:
        client = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER, port=MQTT_PORT)
        client.set_callback(sub_cb)
        client.connect()
        client.subscribe(COMMAND_TOPIC)
        print(f"Connected to MQTT broker {MQTT_BROKER} and subscribed to {COMMAND_TOPIC.decode()}")
        return client
    except OSError as e:
        print(f"Failed to connect to MQTT broker: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during MQTT connection: {e}")
        return None

# --- WIFI Connection ---
WiFIManager = WifiManager()

def connect_wifi_robustly():
    print('Attempting to connect to WiFi...')
    led.value(1)

    WiFIManager.connect() # WifiManager.connect() จะพยายามต่อเอง หรือเข้า AP

    if WiFIManager.is_connected():
        print('Connected to WiFi!')
        led.value(0)
        if str(WiFIManager.get_address()[0]) == '0.0.0.0':
            print('Error: Got 0.0.0.0 IP address. Rebooting device...')
            led.value(0)
            time.sleep(3)
            machine.reset()
    else:
        print("Wi-Fi connection failed and portal didn't resolve. Rebooting...")
        led.value(0)
        time.sleep(3)
        machine.reset()

connect_wifi_robustly()

# เชื่อมต่อ MQTT หลัง Wi-Fi เชื่อมต่อแล้ว

mqtt_initial_retry_count = 0
max_mqtt_initial_retries = 10

while client is None:
    client = connect_and_subscribe()
    if client is None:
        print(f"MQTT connection failed. Retrying in 5 seconds... ({mqtt_initial_retry_count + 1}/{max_mqtt_initial_retries})")
        time.sleep(5)
        mqtt_initial_retry_count += 1
        if mqtt_initial_retry_count >= max_mqtt_initial_retries:
            print("Max initial MQTT retries reached. Rebooting device to try fresh...")
            led.value(0)
            time.sleep(3)
            machine.reset()

status_payload = {
            "version": 3.2,
            "app": "wash",
            "device_type": "wash",
            "ip": str(WiFIManager.get_address()[0]),
            "client_id": get_device_serial_number(),
            "status": "success",
            "message":"online"
}
command_response_topic = b"washing_machine/" + MQTT_CLIENT_ID + b"/command_response"
client.publish(command_response_topic, json.dumps(status_payload).encode())

# Main loop for publishing status and checking for MQTT messages
while True:
    try:
        led.value(1)
        wash_status = json.loads(wash.get_machine_status())
        status_payload = {
            "version": 3.2,
            "app": "wash",
            "device_type": "wash",
            "error_status": False,
            "ip": str(WiFIManager.get_address()[0]),
            "client_id": get_device_serial_number(),
            "status": wash_status
        }
        client.publish(STATUS_TOPIC, json.dumps(status_payload).encode())
        client.check_msg()
        led.value(0)
        time.sleep(5)
    except OSError as e:
        print(f"Network connection error (MQTT/WiFi): {e}. Attempting to recover...")
        led.value(0)
        time.sleep(5)
        machine.reset()

    except Exception as e:
        print(f"An unexpected error occurred in main loop: {e}. Initiating a controlled reboot...")
        led.value(0)
        time.sleep(5)
        machine.reset()

led.value(0)
time.sleep(5)
machine.reset()
