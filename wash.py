import machine
import time
import ujson

RS485_TX_PIN = 17
RS485_RX_PIN = 16

# การตั้งค่า Modbus RTU (ตามเอกสาร)
MODBUS_BAUDRATE = 9600
MODBUS_DATA_BITS = 8
MODBUS_STOP_BITS = 1
MODBUS_PARITY = None # None Parity check
MODBUS_SLAVE_ADDRESS = 1 # Station number: 1-247, สมมติเป็น 1

# ฟังก์ชันสำหรับ CRC16 (ตามมาตรฐาน Modbus RTU)
def calculate_crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, 'little')

class ModbusRTUClient:
    def __init__(self, uart_id=MODBUS_SLAVE_ADDRESS, tx_pin=RS485_TX_PIN, rx_pin=RS485_RX_PIN):
        self.uart = machine.UART(uart_id,baudrate=MODBUS_BAUDRATE, tx=tx_pin, rx=rx_pin,bits=MODBUS_DATA_BITS, stop=MODBUS_STOP_BITS,parity=MODBUS_PARITY)
        self.slave_address = MODBUS_SLAVE_ADDRESS
        time.sleep_ms(100) # รอให้ UART พร้อม

    def _send_modbus_request(self, slave_address, function_code, start_address, quantity_or_value):
        # สร้าง PDU (Protocol Data Unit)
        pdu = bytearray([function_code])
        pdu.extend(start_address.to_bytes(2, 'big'))
        if function_code == 0x03: # Read Holding Registers
            pdu.extend(quantity_or_value.to_bytes(2, 'big'))
        elif function_code == 0x10: # Write Multiple Registers (quantity_or_value คือจำนวน registers)
            num_registers = quantity_or_value
            pdu.extend(num_registers.to_bytes(2, 'big'))
            # ส่วนของ byte_count และ actual data จะถูกเพิ่มในฟังก์ชัน write_multiple_registers
        else:
            raise ValueError("Unsupported function code for _send_modbus_request")

        # สร้าง ADU (Application Data Unit)
        adu = bytearray([slave_address])
        adu.extend(pdu)
        adu.extend(calculate_crc16(adu))

        self.uart.write(adu)
        time.sleep_ms(100) # รอการตอบกลับ

    def _read_modbus_response(self):
        response = bytearray()
        start_time = time.ticks_ms()
        while (time.ticks_ms() - start_time) < 500:
            if self.uart.any():
                response.extend(self.uart.read())
            if len(response) >= 5: # ตรวจสอบความยาวขั้นต่ำ (slave_id + func_code + byte_count/addr + CRC)
                # สำหรับ Function Code 0x03, response[2] คือจำนวน byte ของข้อมูล
                # สำหรับ Function Code 0x10, response จะมี fixed length 8 bytes (slave_id + func_code + start_addr + num_regs + CRC)
                if len(response) >= 3 and response[1] == 0x03 and len(response) >= response[2] + 5:
                    received_crc = int.from_bytes(response[-2:], 'little')
                    calculated_crc = int.from_bytes(calculate_crc16(response[:-2]), 'little')
                    if received_crc == calculated_crc:
                        return response
                elif len(response) == 8 and response[1] == 0x10:
                    received_crc = int.from_bytes(response[-2:], 'little')
                    calculated_crc = int.from_bytes(calculate_crc16(response[:-2]), 'little')
                    if received_crc == calculated_crc:
                        return response
                elif len(response) > 2 and (response[1] & 0x80): # Check for Modbus Exception Response
                    # Exception response: Slave ID (1) + Func Code with error bit (1) + Exception Code (1) + CRC (2) = 5 bytes
                    if len(response) == 5:
                        received_crc = int.from_bytes(response[-2:], 'little')
                        calculated_crc = int.from_bytes(calculate_crc16(response[:-2]), 'little')
                        if received_crc == calculated_crc:
                            #print(f"Modbus Exception: Code {response[2]}")
                            return None # Return None for exception responses
                else:
                    # Not enough data yet or unknown response type, keep reading or timeout
                    pass
        #print("No response or timeout.")
        return None

    def read_holding_registers(self, start_address, quantity):
        """ อ่าน Holding Registers (Function Code: 0x03) """
        self._send_modbus_request(self.slave_address, 0x03, start_address, quantity)
        response = self._read_modbus_response()
        if response and response[1] == 0x03: # ตรวจสอบว่าเป็น response สำหรับ 0x03
            # response format: slave_id (1 byte) + func_code (1 byte) + byte_count (1 byte) + data (N bytes) + CRC (2 bytes)
            # ข้อมูลเริ่มต้นที่ byte ที่ 3 (index 3)
            data_bytes = response[3:-2]
            # แปลง data_bytes เป็น list ของ integers (word)
            registers = []
            for i in range(0, len(data_bytes), 2):
                registers.append(int.from_bytes(data_bytes[i:i+2], 'big'))
            return registers
        return None

    def write_multiple_registers(self, start_address, values):
        """ เขียน Multiple Registers (Function Code: 0x10) """
        byte_count = len(values) * 2
        pdu = bytearray([0x10]) # Function Code: 0x10
        pdu.extend(start_address.to_bytes(2, 'big'))
        pdu.extend(len(values).to_bytes(2, 'big')) # จำนวน Registers
        pdu.extend(byte_count.to_bytes(1, 'big')) # จำนวน Bytes
        for value in values:
            pdu.extend(value.to_bytes(2, 'big'))

        # สร้าง ADU (Application Data Unit)
        adu = bytearray([self.slave_address])
        adu.extend(pdu)
        adu.extend(calculate_crc16(adu))

        self.uart.write(adu)
        response = self._read_modbus_response()
        if response and response[1] == 0x10: # ตรวจสอบว่าเป็น response สำหรับ 0x10
            # สำหรับ Function Code 0x10, response จะเป็น slave_id + func_code + start_addr + num_regs + CRC
            if len(response) == 8:
                # ตรวจสอบว่า start_address และ num_regs ใน response ตรงกับที่ส่งไป
                response_start_addr = int.from_bytes(response[2:4], 'big')
                response_num_regs = int.from_bytes(response[4:6], 'big')
                if response_start_addr == start_address and response_num_regs == len(values):
                    #print("Write successful.")
                    return True
        #print("Write failed or no proper response.")
        return False

# สร้าง Instance ของ Client
modbus_client = ModbusRTUClient()

def get_machine_status():
    status_data = modbus_client.read_holding_registers(20, 40)
    if status_data:
        run_status = status_data[0] # Address 20: Run status
        door_status = status_data[1] # Address 21: Door status
        error_status = status_data[2] # Address 22: Error status
        auto_program_total_remain_time_hour = status_data[3]
        auto_program_total_remain_time_min = status_data[4]
        auto_program_total_remain_time_sec = status_data[5]
        current_inlet_temperature = status_data[6]
        current_outlet_temperature = status_data[7]
        currently_running_program_number = status_data[8]
        currently_running_step_number = status_data[9]
        coins_required_of_currently_selecting_program = status_data[10]
        current_coins = status_data[11]
        total_coins_recorded = status_data[12]
        coins_recorded_in_cash_box = status_data[13]
        matchine_menu = status_data[14]
        coin_inserted = status_data[15]
        must_insert_coin = status_data[16]
        coin_insert = status_data[17]

        run_status_map = {
            0: "Power on",
            1: "Standby",
            2: "N/A", # ตามเอกสารระบุ N/A
            3: "Autorun",
            4: "Manual",
            5: "Idle",
        }
        door_status_map = {
            0: "normal",
            1: "opened",
            2: "closed",
            3: "locked",
            4: "error",
            5: "locking",
        }
        error_status_map = {
            0: "normal", 
            1: "error" 
        }

        response = {
            "app": "wash",
            "version": "WASH_MQTT_1",
            "device_type": "wash",
            "run_status": run_status_map.get(run_status, f"Unknown ({run_status})"),
            "door_status": door_status_map.get(door_status, f"Unknown ({door_status})"),
            "error_status": error_status_map.get(error_status, f"Unknown ({error_status})"),
            "auto_time_hour": auto_program_total_remain_time_hour ,
            "auto_time_min": auto_program_total_remain_time_min ,
            "auto_time_sec": auto_program_total_remain_time_sec ,
            "current_inlet_temperature": current_inlet_temperature ,
            "current_outlet_temperature": current_outlet_temperature ,
            "currently_running_program_number": currently_running_program_number ,
            "currently_running_step_number": currently_running_step_number,
            "coins_required_of_currently_selecting_program": coins_required_of_currently_selecting_program ,
            "current_coins": current_coins ,
            "total_coins_recorded": total_coins_recorded ,
            "coins_recorded_in_cash_box": coins_recorded_in_cash_box , 
            "matchine_menu": matchine_menu ,  
            "must_insert_coin": must_insert_coin ,
            "coin_inserted": coin_inserted ,  
            "coin_insert": coin_insert ,
            "raw_data": status_data,
            "message":"success",
            "error":False
        }
        return ujson.dumps(response)

    status_error = modbus_client.read_holding_registers(60, 9) 
    if status_error:
        response = {
            "app": "wash",
            "version": "WASH_MQTT_1",
            "device_type": "wash",
            "run_status": "N/A",
            "door_status": 4,
            "error_status": 1, 
            "auto_time_hour": 0 , 
            "auto_time_min": 0 ,
            "auto_time_sec": 0,
            "current_inlet_temperature": 0,
            "current_outlet_temperature": 0,
            "currently_running_program_number": 0,
            "currently_running_step_number": 0, 
            "coins_required_of_currently_selecting_program": 0, 
            "current_coins":0, 
            "total_coins_recorded": 0, 
            "coins_recorded_in_cash_box": 0,
            "matchine_menu": 0,
            "must_insert_coin": 0,
            "coin_inserted": 0,
            "coin_insert": 0,
            "raw_data": status_data,
            "raw_erro":status_error,
            "message":"error",
            "error":"Wash Error"
        }
        return ujson.dumps(response)

    response = {
            "app": "wash",
            "version": "WASH_MQTT_1",
            "device_type": "wash",
            "run_status": "error",
            "door_status": 4,
            "error_status": 1, 
            "auto_time_hour": 0 , 
            "auto_time_min": 0 ,
            "auto_time_sec": 0,
            "current_inlet_temperature": 0,
            "current_outlet_temperature": 0,
            "currently_running_program_number": 0,
            "currently_running_step_number": 0, 
            "coins_required_of_currently_selecting_program": 0, 
            "current_coins":0, 
            "total_coins_recorded": 0, 
            "coins_recorded_in_cash_box": 0,
            "matchine_menu": 0,
            "must_insert_coin": 0,
            "coin_inserted": 0,
            "coin_insert": 0,
            "raw_data": status_data,
            "raw_erro": status_error,
            "error":"Modbus Connect Error",
            "message":"เชื่อมต่อเครื่องซักไม่สำเร็จ"}
    return ujson.dumps(response)

def select_program(program_number):
    if not 0 <= program_number <= 30:
        return ujson.dumps({"status": "error", "message": "Invalid program number. For free, must be between 1 and 30."})

    if modbus_client.write_multiple_registers(5, [program_number]):
        return ujson.dumps({"status": "success", "message": f"Selected program {program_number}."})
    return ujson.dumps({"status": "error", "message": "Failed to select program."})
 
def start_operation():
    if modbus_client.write_multiple_registers(1, [1]): # Address 1, Value 1
        return ujson.dumps({"status": "success", "message": "Start command sent."})
    return ujson.dumps({"status": "error", "message": "Failed to send start command."})

def stop_operation():
    if modbus_client.write_multiple_registers(3, [1]): # Address 3, Value 1
        return ujson.dumps({"status": "success", "message": "Stop command sent."})
    return ujson.dumps({"status": "error", "message": "Failed to send stop command."})

def add_coins(amount):
    if not -10 <= amount <= 65535: # Value runge: 0-65535
        return ujson.dumps({"status": "error", "message": "Invalid coin amount. Must be between 0 and 65535."})

    if modbus_client.write_multiple_registers(4, [amount]): # Address 4, Value 'amount'
        return ujson.dumps({"status": "success", "message": f"Added {amount} coins."})
    return ujson.dumps({"status": "error", "message": "Failed to add coins."})

def reset_error():
    if modbus_client.write_multiple_registers(0, [1]): # Address 0, Value 1
        return ujson.dumps({"status": "success", "message": "Error reset command sent."})
    return ujson.dumps({"status": "error", "message": "Failed to send error reset command."})
 
def sendcommand(address,value):
    if modbus_client.write_multiple_registers(address,[value]): # Address 0, Value 1
        return ujson.dumps({"status": "success", "message": "Error reset command sent."})
    return ujson.dumps({"status": "error", "message": "Failed to send error reset command."})

def send_command(address,value):
    if modbus_client.write_multiple_registers(address,[value]): # Address 0, Value 1
        return ujson.dumps({"status": "success", "message": "Error reset command sent."})
    return ujson.dumps({"status": "error", "message": "Failed to send error reset command."})


def write_credentials(name,response):
        with open(str(name)+'.json', 'w') as file:
            file.write(response)

# --- ตัวอย่างการใช้งาน ---
def main():
    #print("--- Getting Machine Status ---")
    status_json = get_machine_status()
    #write_credentials('status',status_json)
    #print(status_json)
    time.sleep(2)

    #print("\n--- Selecting Program (e.g., Program 1) ---")
    select_program_json = select_program(3)
    #write_credentials('select_program',select_program_json)
    #print(select_program_json) 
    time.sleep(2)

    #print("\n--- Adding Coins (e.g., 5 coins) ---")
    add_coins_json = add_coins(4)
    #write_credentials('add_coins',add_coins_json)
    #print(add_coins_json)
    time.sleep(10)

    #print("\n--- Sending Start Command ---")
    start_json = start_operation()
    #write_credentials('start',start_json)
    #print(start_json)
    time.sleep(10)

    #print("\n--- Sending Stop Command ---")
    stop_json = stop_operation()
    #write_credentials('stop',stop_json)
    #print(stop_json)
    time.sleep(2)

    #print("\n--- Resetting Error ---")
    reset_error_json = reset_error()
    #write_credentials('reset_error',reset_error_json)
    #print(reset_error_json)
    time.sleep(2)

    #print("\n--- Getting Machine Status Again ---")
    status_json_after_commands = get_machine_status()
    #print(status_json_after_commands)
