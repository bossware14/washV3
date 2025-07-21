# Author: Igor Ferreira
# License: MIT
# Version: 2.1.0
# Description: WiFi Manager for ESP8266 and ESP32 using MicroPython.
import machine
import network
import socket
import re
import os
import time
import json

def get_device_serial_number():
    try:
        import ubinascii
        return ubinascii.hexlify(machine.unique_id()).decode('utf-8').upper()
    except ImportError:
        return "UNKNOWN_SERIAL"

led = machine.Pin(2, machine.Pin.OUT,value=0)
class WifiManager:

    def __init__(self, ssid = "WASH-"+str(get_device_serial_number()) , password = "12345678", reboot = True, debug = False):
        self.wlan_sta = network.WLAN(network.STA_IF)
        self.wlan_sta.active(True)
        self.wlan_ap = network.WLAN(network.AP_IF)
        
        # Avoids simple mistakes with wifi ssid and password lengths, but doesn't check for forbidden or unsupported characters.
        if len(ssid) > 32:
            raise Exception('The SSID cannot be longer than 32 characters.')
        else:
            self.ap_ssid = ssid
        if len(password) < 8:
            raise Exception('The password cannot be less than 8 characters long.')
        else:
            self.ap_password = password
            
        # Set the access point authentication mode to WPA2-PSK.
        self.ap_authmode = 3
        
        # The file were the credentials will be stored.
        # There is no encryption, it's just a plain text archive. Be aware of this security problem!
        self.wifi_credentials = 'wifi.dat'
        
        # Prevents the device from automatically trying to connect to the last saved network without first going through the steps defined in the code.
        self.wlan_sta.disconnect()
        
        # Change to True if you want the device to reboot after configuration.
        # Useful if you're having problems with web server applications after WiFi configuration.
        self.reboot = reboot
        
        self.debug = debug


    def connect(self):
        if self.wlan_sta.isconnected():
            return
        profiles = self.read_credentials()
        for ssid, *_ in self.wlan_sta.scan():
            ssid = ssid.decode("utf-8")
            if ssid in profiles:
                password = profiles[ssid]
                if self.wifi_connect(ssid, password):
                    return
        print('Could not connect to any WiFi network. Starting the configuration portal...')
        self.web_server()
        
    
    def disconnect(self):
        if self.wlan_sta.isconnected():
            self.wlan_sta.disconnect()


    def is_connected(self):
        return self.wlan_sta.isconnected()


    def get_address(self):
        return self.wlan_sta.ifconfig()


    def write_credentials(self, profiles):
        lines = []
        for ssid, password in profiles.items():
            lines.append('{0};{1}\n'.format(ssid, password))
        with open(self.wifi_credentials, 'w') as file:
            file.write(''.join(lines))

    def write_config(self, data):
        f = open('config.json','w') 
        f.write(data) 
        f.close()
        
    def read_credentials(self):
        lines = []
        try:
            with open(self.wifi_credentials) as file:
                lines = file.readlines()
        except Exception as error:
            if self.debug:
                print(error)
            pass
        profiles = {}
        for line in lines:
            ssid, password = line.strip().split(';')
            profiles[ssid] = password
        return profiles


    def wifi_connect(self, ssid, password):
        print('Trying to connect to:', ssid)
        self.wlan_sta.connect(ssid, password)
        time.sleep(1)
        for _ in range(100):
            if self.wlan_sta.isconnected():
                print('\nConnected! Network information:', self.wlan_sta.ifconfig())
                led.value(1)
                return True
            else:
                if led.value() == 0 :
                    led.value(1)
                else :
                    led.value(0)
                print('.', end='')
                time.sleep_ms(100)
                
        print('\nConnection failed!')
        led.value(0)
        self.wlan_sta.disconnect()
        time.sleep(5)
        machine.reset()
        return False

    
    def web_server(self):
        self.wlan_ap.active(True)
        self.wlan_ap.config(essid = self.ap_ssid, password = self.ap_password, authmode = self.ap_authmode)
        server_socket = socket.socket()
        server_socket.close()
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('', 80))
        server_socket.listen(10) 
        print('Connect to', self.ap_ssid, 'with the password', self.ap_password, 'and access the captive portal at', self.wlan_ap.ifconfig()[0])
        # เพิ่มตัวแปรสำหรับจับเวลาเริ่มต้น
        start_time = time.time()
        while True:
            # ตรวจสอบว่าผ่านไป 3 นาทีแล้วหรือยัง
            if (time.time() - start_time) > 60: # 180 วินาที = 3 นาที
                print("3 นาทีผ่านไป, กำลังรีสตาร์ทอุปกรณ์...")
                machine.reset()
            
            if self.wlan_sta.isconnected():
                self.wlan_ap.active(False)
                if self.reboot:
                    print('The device will reboot in 5 seconds.')
                    time.sleep(5)
                    machine.reset()

            self.client, addr = server_socket.accept()
            try:
                self.client.settimeout(5.0)
                self.request = b''
                try:
                    while True:
                        if '\r\n\r\n' in self.request:
                            # Fix for Safari browser
                            self.request += self.client.recv(512) 
                            break
                        self.request += self.client.recv(128)
                except Exception as error:
                    # It's normal to receive timeout errors in this stage, we can safely ignore them.
                    if self.debug:
                        print(error)
                    pass
                if self.request:
                    if self.debug:
                        print(self.url_decode(self.request))
                    url = re.search('(?:GET|POST) /(.*?)(?:\\?.*?)? HTTP', self.request).group(1).decode('utf-8').rstrip('/')
                    if url == '':
                        self.handle_root()
                    elif url == 'configure':
                        self.handle_configure()
                    else:
                        self.handle_not_found()
            except Exception as error:
                if self.debug:
                    print(error)
                print("disconnect_reboot")
                time.sleep(5)
                machine.reset()
                return
            finally:
                self.client.close()


    def send_header(self, status_code = 200):
        self.client.send("""HTTP/1.1 {0} OK\r\n""".format(status_code))
        self.client.send("""Content-Type: text/html\r\n""")
        self.client.send("""Connection: close\r\n""")


    def send_response(self, payload, status_code = 200):
        self.send_header(status_code)
        self.client.sendall("""
            <!DOCTYPE html>
            <html lang="en">
                <head>
                    <title>WiFi Manager</title>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <link rel="icon" href="data:,">
                </head>
                <body>
                    {0}
                </body>
            </html>
        """.format(payload))
        self.client.close()


    def handle_root(self):
        self.send_header()
        self.client.sendall("""
            <!DOCTYPE html>
            <html lang="en" style="font-family: Arial, Helvetica, sans-serif;display: inline-block;text-align: center;">
                <head>
                    <title>WiFi Manager</title>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <link rel="icon" href="data:,">
                </head>
                <body style="font-size:1.4rem">
                <form action="/configure" method="POST" accept-charset="utf-8">
                    <div class="topnav">
                    <h1 style="background-color: #0A1128;font-size: 1.6rem;color: white;padding: 2px;margin: 0px;">เชื่อมต่อ WiFi</h1>
                    </div>
                    <div class="content">
                    <div class="card-grid" style="max-width: 800px;margin: 0 auto;display: grid;grid-gap: 2rem;grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));">
                    <div class="card" style="background-color: white;box-shadow: 2px 2px 12px 1px rgba(140, 140, 140, .5);">
                    <div class="row" style="display: flex;height: 60px;">
                            <div class="col-30" style="display: inline-block;width: 30%;align-self: center;">
                            <label for="ssid">WiFi</label>
                            </div>
                            <div class="col-70" style="display: inline-block;width: 70%;align-self: center;">
                            <select id="ssid" name="ssid" style="font-size: 1rem;width: 90%;padding: 12px 20px;margin: 18px;display: inline-block;border: 1px solid #ccc;border-radius: 4px;box-sizing: border-box;">
        """.format(self.ap_ssid))
        for ssid, *_ in self.wlan_sta.scan():
            ssid = ssid.decode("utf-8")
            self.client.sendall("""
                    <option  value="{0}">&nbsp;{0}</option>
            """.format(ssid))
        self.client.sendall("""
                            </select>
                            </div>
                            </div>
                                <div class="row" style="display: flex;height: 60px;">
                                    <div class="col-30" style="display: inline-block;width: 30%;align-self: center;">
                                        <label for="password">รหัสผ่าน</label>
                                    </div>
                                    <div class="col-70" style="display: inline-block;width: 70%;align-self: center;">
                                        <input type="text" placeholder="รหัสผ่าน Wifi"  id="password" name="password" style="width: 90%;padding: 12px 20px;margin: 18px;display: inline-block;border: 1px solid #ccc;border-radius: 4px;box-sizing: border-box;font-size: 1rem;">
                                    </div>
                                </div>
                                
                                <div class="row" style="display: flex;height: 60px;">
                                    <div class="col-30" style="display: inline-block;width: 30%;align-self: center;">
                                        <label for="select">ประเภท</label>
                                    </div>
                                    <div class="col-70" style="display: inline-block;width: 70%;align-self: center;">
                                        <select id="select" name="select" style="width: 90%;padding: 12px 20px;margin: 18px;display: inline-block;border: 1px solid #ccc;border-radius: 4px;box-sizing: border-box;font-size: 1rem;">
                                        <option value="wash">เครื่อง ซักผ้า</option>
                                        <option value="dryer">เครื่อง อบผ้า</option>
                                        </select>
                                    </div>
                                </div>
                                
                                <div class="">
                                    <input type ="submit" style="border: none;color: #FEFCFB;background-color: #034078;padding: 15px 15px;text-align: center;text-decoration: none;display: inline-block;font-size: 16px;width: 100px;margin-right: 10px;margin-bottom: 20px;border-radius: 4px;transition-duration: 0.4s;font-size: 1rem;" value="Connect" class="btn">
                                </div>
                    </div>
                    </div>
                    </div>
                    </form>
                </body>
            </html>
        """)
        self.client.close()

    def handle_configure(self):
        match = re.search('ssid=([^&]*)&password=(.*)&select=(.*)', self.url_decode(self.request))
        if match:
            ssid = match.group(1).decode('utf-8')
            password = match.group(2).decode('utf-8')
            select = match.group(3).decode('utf-8')
            if len(ssid) == 0:
                self.send_response("""
                    <p>SSID must be providaded!</p>
                    <p>Go back and try again!</p>
                """, 400)
            elif self.wifi_connect(ssid, password):
                self.send_response("""
                    <p>Successfully connected to</p>
                    <h1>{0}</h1>
                    <p>IP address: {1}</p>
                """.format(ssid, self.wlan_sta.ifconfig()[0]))
                profiles = self.read_credentials()
                profiles[ssid] = password
                self.write_credentials(profiles)
                data = {"ssid":ssid,"pwd":password}
                self.write_config(json.dumps(data))
                
                import requests

                boot_update = requests.get('http://34.124.162.209/espV3/boot.txt')
                if boot_update.status_code == 200:
                    with open('boot.py','w') as f:
                        f.write(boot_update.text)

                main_update = requests.get('http://34.124.162.209/espV3/main.txt')
                if main_update.status_code == 200:
                    with open('main.py','w') as f:
                        f.write(main_update.text)

                if select == 'wash' :
                    wash_update = requests.get('http://34.124.162.209/espV3/wash.txt')
                    if wash_update.status_code == 200:
                        with open('wash.py','w') as f:
                            f.write(wash_update.text)
                            
                if select == 'dryer' :
                    dryer_update = requests.get('http://34.124.162.209/espV3/dryer.txt')
                    if dryer_update.status_code == 200:
                        with open('wash.py','w') as f:
                            f.write(dryer_update.text)
                            
                print(select)
                time.sleep(5)
            else:
                self.send_response("""
                    <p>Could not connect to</p>
                    <h1>{0}</h1>
                    <p>Go back and try again!</p>
                """.format(ssid))
                time.sleep(5)
        else:
            self.send_response("""
                <p>Parameters not found!</p>
            """, 400)
            time.sleep(5)

    def resetPass(self):
        self.send_response("""
            <p>Page not found!</p>
        """, 404)


    def handle_not_found(self):
        self.send_response("""
            <p>Page not found!</p>
        """, 404)


    def url_decode(self, url_string):

        if not url_string:
            return b''

        if isinstance(url_string, str):
            url_string = url_string.encode('utf-8')

        bits = url_string.split(b'%')

        if len(bits) == 1:
            return url_string

        res = [bits[0]]
        appnd = res.append
        hextobyte_cache = {}

        for item in bits[1:]:
            try:
                code = item[:2]
                char = hextobyte_cache.get(code)
                if char is None:
                    char = hextobyte_cache[code] = bytes([int(code, 16)])
                appnd(char)
                appnd(item[2:])
            except Exception as error:
                if self.debug:
                    print(error)
                appnd(b'%')
                appnd(item)

        return b''.join(res)
