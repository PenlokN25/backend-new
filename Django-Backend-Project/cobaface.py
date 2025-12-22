from RPLCD.i2c import CharLCD
import lgpio
import time
import subprocess
from gpiozero import OutputDevice
import threading
from threading import Thread
import serial
import threading
import psycopg2
import os
import datetime
import paho.mqtt.client as mqtt
import json
import face

# --- Database Configuration ---
# Konfigurasi database sekarang menggunakan localhost dan port 1723 sesuai dengan Docker
DB_NAME = os.getenv("PG_DB", "smartlocker") # Mengikuti nama DB di Django
DB_USER = os.getenv("PG_USER", "smartlocker_admin") # Mengikuti konfigurasi di Django
DB_PASSWORD = os.getenv("PG_PASSWORD", "penlokjaya") # Mengikuti konfigurasi di Django
DB_HOST = os.getenv("DB_HOST", "localhost") # Menggunakan localhost agar bisa terhubung ke Docker
DB_PORT = os.getenv("DB_PORT", "1723") # Menggunakan port forwarding Docker

# --- MQTT Setup ---
MQTT_BROKER_HOST = "localhost"
MQTT_BROKER_PORT = 1883
MQTT_TOPIC_COMMAND = "penlok/command"

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Terhubung ke MQTT Broker!")
        client.subscribe(MQTT_TOPIC_COMMAND)
        print(f"Berlangganan topik: {MQTT_TOPIC_COMMAND}")
    else:
        print(f"Gagal terhubung, kode status: {rc}")

def on_message(client, userdata, msg):
    print(f"Pesan diterima dari topik {msg.topic}: {msg.payload.decode()}")
    try:
        data = json.loads(msg.payload.decode())
        action = data.get("action")
        locker_number = data.get("locker_number")

        if action == "open" and locker_number in LOCKER_RELAY_MAP:
            print(f"Membuka loker nomor: {locker_number}")
            relay_to_trigger = LOCKER_RELAY_MAP[locker_number]
            trigger_relay(relay_to_trigger, 1)
            print(f"Loker {locker_number} telah dibuka.")
        else:
            print(f"Aksi tidak dikenal '{action}' atau loker '{locker_number}' tidak valid.")

    except json.JSONDecodeError:
        print("Gagal mem-parsing JSON dari pesan MQTT.")
    except Exception as e:
        print(f"Terjadi error saat memproses pesan MQTT: {e}")

def setup_mqtt_client():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
        # Menjalankan loop di thread terpisah
        threading.Thread(target=client.loop_forever, daemon=True).start()
    except Exception as e:
        print(f"Tidak dapat terhubung ke MQTT Broker: {e}")

# Inisialisasi pin relay (aktif LOW)
relay_1 = OutputDevice(6, active_high=False, initial_value=False)#l3
relay_2 = OutputDevice(9, active_high=False, initial_value=False)#l2
relay_3 = OutputDevice(10, active_high=False, initial_value=False)#l1
relay_4 = OutputDevice(19, active_high=False, initial_value=False)#lb

# Mapping dari nomor loker (string) ke objek relay
# Konsisten dengan nomor loker di database Django
LOCKER_RELAY_MAP = {
    "0": relay_4,  # Inbound/outbound loker dihubungkan ke relay_1 (GPIO 6)
    "1": relay_3,  # Loker 1 dihubungkan ke relay_2 (GPIO 9)
    "2": relay_2,  # Loker 2 dihubungkan ke relay_3 (GPIO 10)
    "3": relay_1,  # Loker 3 dihubungkan ke relay_4 (GPIO 19)
}

# Hubungkan ke Arduino
try:
    arduino = serial.Serial('/dev/ttyACM0', 9600, timeout=1)  # atau ttyUSB0 sesuai device kamu
    print("Arduino terhubung!")
except Exception as e:
    print("Gagal terhubung ke Arduino:", e)
    arduino = None


def trigger_relay(relay, delay=1):
    relay.on()
    time.sleep(delay)
    relay.off()

# Setup LCD
lcd = CharLCD('PCF8574', 0x27)

# Setup Keypad
COLUMNS = [8, 25, 11]
ROWS = [5, 1, 0, 7]
KEYS = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
    ['*', '0', '#']
]

def poll_locker_requests():
    """
    Fungsi untuk polling permintaan pembukaan loker dari database
    """
    while True:
        try:
            # Ambil permintaan terbaru yang belum diproses
            conn = psycopg2.connect(
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port=DB_PORT
            )
            cur = conn.cursor()

            # Query semua permintaan yang belum diproses
            cur.execute("""
                SELECT locker_number
                FROM lockers_lockerrequest
                WHERE fulfilled = false
                ORDER BY requested_at DESC
            """)
            unfulfilled_requests = cur.fetchall()

            for request in unfulfilled_requests:
                locker_number = request[0]
                if locker_number in LOCKER_RELAY_MAP:
                    print(f"Membuka loker nomor: {locker_number} berdasarkan permintaan dari database")
                    relay_to_trigger = LOCKER_RELAY_MAP[locker_number]
                    trigger_relay(relay_to_trigger, 1)
                    print(f"Loker {locker_number} telah dibuka.")

                    # Tandai permintaan sebagai sudah diproses
                    cur.execute("""
                        UPDATE lockers_lockerrequest
                        SET fulfilled = true, fulfilled_at = NOW()
                        WHERE locker_number = %s AND fulfilled = false
                        """, (locker_number,))
                    conn.commit()

            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error saat polling permintaan loker: {e}")

        time.sleep(2)  # Tunggu 2 detik sebelum polling lagi

# Setup GPIO
PIN_BUTTON = 16
PIN_BUZZER = 21
PIN_RED = 23
PIN_GREEN = 22
led_red = 18
led_green = 27
PIN_GETAR = 24
TRIG_PIN = 15
ECHO_PIN = 17
DETECTION_THRESHOLD_CM = 7.5

# Loadcell setup
DOUT = 4
SCK = 14
OFFSET = 8763202    # Tara (kosong) 111g
SCALE = 196.584     # Faktor kalibrasi per gram

gpio_hcsr_handle = lgpio.gpiochip_open(0)
h = lgpio.gpiochip_open(0)

for pin in COLUMNS:
    lgpio.gpio_claim_output(h, pin, 0)
for pin in ROWS:
    lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_DOWN)

lgpio.gpio_claim_output(h, PIN_RED, 1)
lgpio.gpio_claim_output(h, PIN_GREEN, 1)
lgpio.gpio_claim_output(h, led_red, 1)
lgpio.gpio_claim_output(h, led_green, 1)
lgpio.gpio_claim_output(h, PIN_BUZZER, 0)
lgpio.gpio_claim_input(h, PIN_BUTTON, lgpio.SET_PULL_UP)
lgpio.gpio_claim_input(h, PIN_GETAR)
last_press_time = 0
DEBOUNCE_DELAY = 0.3  # dalam detik
lgpio.gpio_claim_output(gpio_hcsr_handle, TRIG_PIN)
lgpio.gpio_claim_input(gpio_hcsr_handle, ECHO_PIN)
lgpio.gpio_write(gpio_hcsr_handle, TRIG_PIN, 0)

# Setup GPIO for loadcell
lgpio.gpio_claim_input(h, DOUT)
lgpio.gpio_claim_output(h, SCK, 0)
time.sleep(0.2)

def indikator_salah():
    # LED merah dan buzzer nyala 2 detik sebanyak 3x
    for _ in range(3):
        lgpio.gpio_write(h, PIN_RED, 0)
        lgpio.gpio_write(h, PIN_GREEN, 1)
        lgpio.gpio_write(h, PIN_BUZZER, 1)
        time.sleep(0.2)
        lgpio.gpio_write(h, PIN_RED, 1)
        lgpio.gpio_write(h, PIN_BUZZER, 0)
        time.sleep(0.2)  # jeda antar bunyi

def indikator_benar():
    # LED hijau dan buzzer menyala 5 detik
    lgpio.gpio_write(h, PIN_GREEN, 0)
    lgpio.gpio_write(h, PIN_RED, 1)
    lgpio.gpio_write(h, PIN_BUZZER, 1)
    time.sleep(1)
    lgpio.gpio_write(h, PIN_GREEN, 1)
    lgpio.gpio_write(h, PIN_BUZZER, 0)

# Loadcell functions
def read_hx711():
    """
    Fungsi membaca HX711
    """
    count = 0
    lgpio.gpio_write(h, SCK, 0)
    while lgpio.gpio_read(h, DOUT) == 1:
        pass
    for i in range(24):
        lgpio.gpio_write(h, SCK, 1)
        count = count << 1
        lgpio.gpio_write(h, SCK, 0)
        if lgpio.gpio_read(h, DOUT):
            count += 1
    lgpio.gpio_write(h, SCK, 1)
    count ^= 0x800000
    lgpio.gpio_write(h, SCK, 0)
    return count

def get_average_loadcell(samples=10):
    """
    Ambil rata-rata pembacaan loadcell
    """
    total = 0
    for _ in range(samples):
        total += read_hx711()
        time.sleep(0.05)
    return total / samples

def monitor_loadcell():
    """
    Fungsi untuk monitor berat dengan toleransi 5 gram
    Hanya menampilkan pembacaan ketika perbedaan melebihi 5 gram dari pembacaan sebelumnya
    """
    last_displayed_weight = None  # Simpan berat terakhir yang ditampilkan
    TOLERANCE = 5.0  # Toleransi 5 gram

    while True:
        try:
            raw = get_average_loadcell()
            current_weight = (raw - OFFSET) / SCALE

            # Jika ini adalah pembacaan pertama, atau jika perbedaan melebihi toleransi
            if last_displayed_weight is None or abs(current_weight - last_displayed_weight) >= TOLERANCE:
                print(f"Berat terdeteksi: {current_weight:.2f} gram")
                last_displayed_weight = current_weight  # Update berat terakhir yang ditampilkan

            time.sleep(1)  # Baca setiap detik
        except Exception as e:
            print(f"Error saat membaca loadcell: {e}")
            time.sleep(1)  # Tetap lanjutkan meskipun ada error

def monitor_arduino():
    if not arduino:
        return
    while True:
        try:
            line = arduino.readline().decode('utf-8').strip()
            if line:
                print("[ARDUINO] >", line)
                if line.startswith("ULTRA:DETECTED"):
                    print("🔔 Barang terdeteksi di loker 3")
                    #subprocess.run(["python3", "infra_servo.py"])
                elif line.startswith("IR:DETECTED"):
                    print("🔔 Pintu loker 3 tertutup")
                    indikator_salah()
                elif line.startswith("RFID:ACCEPTED"):
                    uid = line.split(":")[2]
                    print(f"✅ RFID diterima UID: {uid}")
                    indikator_benar()
                    trigger_relay(relay_4, 1)
                elif line.startswith("RFID:DENIED"):
                    uid = line.split(":")[2]
                    print(f"❌ RFID ditolak UID: {uid}")
                    indikator_salah()
        except Exception as e:
            print("Error baca serial Arduino:", e)
        time.sleep(0.2)
threading.Thread(target=monitor_arduino, daemon=True).start()

def get_distance():
    lgpio.gpio_write(gpio_hcsr_handle, TRIG_PIN, 1)
    time.sleep(0.00001)
    lgpio.gpio_write(gpio_hcsr_handle, TRIG_PIN, 0)

    pulse_start = time.time()
    pulse_end = time.time()

    timeout_start_high = time.time()
    while lgpio.gpio_read(gpio_hcsr_handle, ECHO_PIN) == 0:
        pulse_start = time.time()
        if time.time() - timeout_start_high > 0.1:
            return -1

    timeout_start_low = time.time()
    while lgpio.gpio_read(gpio_hcsr_handle, ECHO_PIN) == 1:
        pulse_end = time.time()
        if time.time() - timeout_start_low > 0.1:
            return -1

    pulse_duration = pulse_end - pulse_start
    distance = (pulse_duration * 34300) / 2
    return distance


def read_key():
    for col_idx, col_pin in enumerate(COLUMNS):
        lgpio.gpio_write(h, col_pin, 1)
        for row_idx, row_pin in enumerate(ROWS):
            if lgpio.gpio_read(h, row_pin) == 1:
                lgpio.gpio_write(h, col_pin, 0)
                return KEYS[row_idx][col_idx]
        lgpio.gpio_write(h, col_pin, 0)
    return None

def wait_key():
    key = None
    while key is None:
        key = read_key()
        time.sleep(0.05)
    while read_key() is not None:
        time.sleep(0.05)
    return key


face_menu_requested = False
face_star_streak = 0


class FaceMenuExit(Exception):
    """Dilempar ketika user menekan * tiga kali berturut-turut."""


def face_display_lines(lines):
    lcd.clear()
    for idx, text in enumerate(lines[:4]):
        lcd.cursor_pos = (idx, 0)
        lcd.write_string(text[:16].ljust(16))


def face_show_temp_message(lines, delay=2):
    face_display_lines(lines)
    time.sleep(delay)


def face_wait_key():
    global face_star_streak
    key = wait_key()
    if key == '*':
        face_star_streak += 1
        if face_star_streak >= 3:
            raise FaceMenuExit
    else:
        face_star_streak = 0
    return key


def face_input_digits(title, max_digits):
    digits = ""
    while True:
        face_display_lines([
            title[:16],
            (digits or "-")[:16],
            "#=OK  *=Hapus",
            "* x3 Menu Utama",
        ])
        key = face_wait_key()
        if key == '#':
            if digits:
                return digits
        elif key == '*':
            if digits:
                digits = digits[:-1]
            else:
                return None
        elif key and key.isdigit() and len(digits) < max_digits:
            digits += key


def face_input_number(title, min_value=1, max_value=20):
    digits = ""
    while True:
        face_display_lines([
            title[:16],
            f"Min {min_value} Max {max_value}"[:16],
            (digits or "-")[:16],
            "#=OK  *=Batal",
        ])
        key = face_wait_key()
        if key == '#':
            if digits:
                value = int(digits)
                if min_value <= value <= max_value:
                    return value
        elif key == '*':
            if digits:
                digits = digits[:-1]
            else:
                return None
        elif key and key.isdigit() and len(digits) < 2:
            digits += key


def face_confirm_yes_no(line1, line2=""):
    face_display_lines([
        line1[:16],
        line2[:16],
        "1=Ya   2=Tidak",
        "* x3 Menu Utama",
    ])
    while True:
        key = face_wait_key()
        if key == '1':
            return True
        if key == '2':
            return False
        if key == '#':
            return False
        if key == '*':
            return False


def face_show_user_info(user_data, face_id):
    username = user_data.get("username", "-")
    full_name = f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip()
    role = user_data.get("role", "-")
    face_display_lines([
        "User ditemukan",
        f"User: {username[:10]}",
        f"ID: {face_id[:10]}",
        f"Role: {role[:10]}",
    ])
    time.sleep(2)


def face_prompt_start(message="Tekan # utk mulai"):
    face_display_lines([
        message[:16],
        "#=Mulai *=Batal",
        "* x3 Menu Utama",
        "",
    ])
    while True:
        key = face_wait_key()
        if key == '#':
            return True
        if key == '*':
            return False

def monitor_ultrasonic():
    last_status = None
    while True:
        distance = get_distance()
        if distance != -1:
            if distance < DETECTION_THRESHOLD_CM:
                status = "🔔 Barang terdeteksi di loker 1"
                if status != last_status:
                    print(f"Distance: {distance:.2f} cm")
                    print(f"Locker Status: {status}")
                    last_status = status
                    time.sleep(3)
                    try:
                        subprocess.run(["python3", "infra_servogpio0.py"])
                    except Exception as e:
                        print("Gagal menjalankan servo.py:", e)
                    # New approach with separate IR monitoring and servo control
                    try:
                        subprocess.run(["python3", "ir_monitor.py"], timeout=20)
                    except subprocess.TimeoutExpired:
                        print("IR monitor timed out")
                    except Exception as e:
                        print("Gagal menjalankan ir_monitor.py:", e)
            else:
                last_status = "EMPTY"
        time.sleep(1)
# Mulai pemantauan sensor ultrasonic
Thread(target=monitor_ultrasonic, daemon=True).start()

def monitor_getar():
    while True:
        val = lgpio.gpio_read(h, PIN_GETAR)
        if val == 1:
            print("Getaran TERDETEKSI!")
        time.sleep(0.2)
# Mulai thread pemantauan getaran
threading.Thread(target=monitor_getar, daemon=True).start()

def cek_push_button():
    global last_press_time, face_menu_requested
    if lgpio.gpio_read(h, PIN_BUTTON) == 0:
        now = time.time()
        if now - last_press_time > DEBOUNCE_DELAY:
            print("Tombol owner ditekan - membuka menu wajah")
            last_press_time = now
            face_menu_requested = True
            return True
    return False


def face_handle_training_flow():
    face_display_lines([
        "FACE TRAINING",
        "Masukkan Face ID",
        "#=OK  *=Kembali",
        "* x3 Menu Utama",
    ])
    face_id = face_input_digits("Face ID (#=OK)", 8)
    if not face_id:
        face_show_temp_message(["Input dibatalkan"], 1.5)
        return

    face_display_lines(["Cari user...", "", "", ""])
    status_code, user_data = face.get_user_by_faceid(face_id)
    if status_code != 200 or not user_data:
        face_show_temp_message([
            "User tidak ada",
            f"Status: {status_code}",
            "",
            "",
        ], 2)
        return

    face_show_user_info(user_data, face_id)
    if not face_confirm_yes_no("Lanjut training?"):
        face_show_temp_message(["Dibatalkan"], 1.5)
        return

    username = user_data.get("username")
    if not username:
        face_show_temp_message(["Username kosong"], 1.5)
        return

    status_img, resp_img = face.check_user_images(username)
    if status_img == 200:
        existing = len(resp_img.get("data", [])) if isinstance(resp_img, dict) else 0
        face_show_temp_message([
            "Mode tambahan",
            f"Ada: {existing}",
            "",
            "",
        ], 2)
    elif status_img == 403:
        face_show_temp_message([
            "Mode baru",
            "Belum ada data",
            "",
            "",
        ], 2)
    else:
        face_show_temp_message([
            "Gagal cek data",
            f"Status: {status_img}",
            "",
            "",
        ], 2)
        return

    target_images = face_input_number("Jumlah gambar", 1, 20)
    if not target_images:
        face_show_temp_message(["Tidak ada jumlah"], 1.5)
        return

    verified_images = []
    attempt = 1
    try:
        while len(verified_images) < target_images:
            remaining = target_images - len(verified_images)
            face_display_lines([
                f"Batch {attempt}",
                f"Butuh: {remaining}",
                "ESC=Batalkan GUI",
                "* x3 Menu Utama",
            ])
            captured = face.auto_capture_images(username, remaining)
            if not captured:
                face_show_temp_message(["Capture dibatalkan"], 2)
                break
            verified_images.extend(captured)
            attempt += 1
            if attempt > 10:
                face_show_temp_message(["Percobaan habis"], 2)
                break

        if len(verified_images) >= target_images:
            face_display_lines(["Upload ke server", "", "", ""])
            status_upload, response = face.upload_images_to_server(username, verified_images)
            if status_upload == 200 and isinstance(response, dict):
                total = len(response.get("data", []))
                face_show_temp_message([
                    "Upload sukses",
                    f"Total: {total}",
                    "",
                    "",
                ], 3)
            elif status_upload == 200:
                face_show_temp_message([
                    "Upload sukses",
                    "",
                    "",
                    "",
                ], 3)
            else:
                face_show_temp_message([
                    "Upload gagal",
                    f"Status {status_upload}",
                    "",
                    "",
                ], 3)
        else:
            face_show_temp_message([
                "Data kurang",
                "Tidak tersimpan",
                "",
                "",
            ], 2)
    finally:
        face.cleanup_temp_files(username)


def face_handle_verification_flow():
    if not face_prompt_start("Verifikasi wajah"):
        face_show_temp_message(["Batal"], 1.5)
        return

    face_display_lines(["Ambil gambar...", "", "", ""])
    image_path = face.capture_single_image_with_verification()
    if not image_path:
        face.cleanup_face_log_temp()
        face_show_temp_message(["Gagal ambil foto"], 2)
        return

    status_code, response = face.send_face_log_to_server(image_path)
    face.cleanup_face_log_temp()

    if status_code == 200 and isinstance(response, dict):
        result = response.get("result", [])
        confidence = response.get("confidence", "N/A")
        if result:
            log_data = result[0]
            status = log_data.get("status", "Unknown")
            user_id = log_data.get("id_face_user", "-")
            message = "AUTHORIZED" if status.lower() == "authorized" else "UNAUTHORIZED"
            face_show_temp_message([
                message,
                f"Conf: {confidence}",
                f"User: {user_id}",
                "",
            ], 3)
        else:
            face_show_temp_message([
                "Resp tidak lengkap",
                "",
                "",
                "",
            ], 2)
    else:
        face_show_temp_message([
            "Verifikasi gagal",
            f"Status {status_code}",
            "",
            "",
        ], 3)


def face_menu_loop():
    global face_star_streak
    face_star_streak = 0
    try:
        while True:
            face_display_lines([
                "FACE MENU",
                "1=Regis/Tambah",
                "2=Verifikasi",
                "* x3 Menu Utama",
            ])
            key = face_wait_key()
            if key == '1':
                face_handle_training_flow()
            elif key == '2':
                face_handle_verification_flow()
            elif key == '#':
                face_show_temp_message(["Gunakan opsi 1/2"], 1)
    except FaceMenuExit:
        face_show_temp_message(["Keluar face menu"], 1.5)
        return 'menu_utama'
    return 'menu_utama'


def verify_tracking_id_from_db(input_id):
    conn = None
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cur = conn.cursor()
        # Query untuk memeriksa 5 digit terakhir dari tracking_number
        # Menggunakan RIGHT() untuk mengambil 5 karakter terakhir
        cur.execute(
            "SELECT 1 FROM package_center_packageentry WHERE RIGHT(tracking_number, 5) = %s;",
            (input_id,)
        )
        result = cur.fetchone()
        cur.close()
        return result is not None
    except Exception as e:
        print(f"Error connecting to or querying database: {e}")
        return False
    finally:
        if conn:
            conn.close()

def menu_utama():
    lcd.clear()
    lcd.cursor_pos = (0, 4)
    lcd.write_string("  BoxInAja")
    lcd.cursor_pos = (1, 0)
    lcd.write_string("Pilih opsi di bawah!")
    lcd.cursor_pos = (2, 0)
    lcd.write_string("1. Kirim Paket")
    lcd.cursor_pos = (3, 0)
    lcd.write_string("2. Ambil Paket")

def menu_kirim():
    lcd.clear()
    lcd.write_string("Kirim Paket")
    lcd.cursor_pos = (1, 0)
    lcd.write_string("1. Scan QR")
    lcd.cursor_pos = (2, 0)
    lcd.write_string("2. Masukkan Resi")
    lcd.cursor_pos = (3, 0)
    lcd.write_string("*. Kembali")

def menu_scan_qr():
    lcd.clear()
    lcd.write_string("Scan kode QR")
    lcd.cursor_pos = (1, 0)
    lcd.write_string("Tekan tombol merah")
    time.sleep(0.5)

    # Jalankan script kamera dan tangkap hasil exit code
    try:
        result = subprocess.run(["python3", "cobav2.py"])
        exit_code = result.returncode
    except Exception as e:
        lcd.cursor_pos = (1, 0)
        lcd.write_string("Error kamera")
        print("Gagal menjalankan kamera:", e)
        time.sleep(2)
        return 'menu_utama'

    # Delay tergantung apakah tombol ditekan atau tidak
    if exit_code == 0:
        time.sleep(2)  # tombol ditekan
    else:
        time.sleep(7)  # tombol tidak ditekan

    lcd.clear()
    lcd.write_string("Selesai Scan QR")
    lcd.cursor_pos = (1, 0)
    lcd.write_string("Kembali ke menu")
    #indikator_benar()
    trigger_relay(relay_3, 3)#coba aslinya 3
    time.sleep(2)
    return 'menu_utama'

def menu_input_id(kembali_ke):
    lcd.clear()
    lcd.write_string("Input 5 digit akhir")
    lcd.cursor_pos = (3, 0)
    lcd.write_string("#. Hapus  *. Kembali")
    input_id = ""

    while True:
        lcd.cursor_pos = (1, 0)
        lcd.write_string(" " * 16)
        lcd.cursor_pos = (1, 0)
        lcd.write_string(input_id)

        key = wait_key()

        if key == '*':
            return kembali_ke
        elif key == '#':
            input_id = ""
        elif key and len(input_id) < 5: # Batasi input menjadi 5 digit
            input_id += key

        lcd.cursor_pos = (1, 0)
        lcd.write_string(" " * 16)
        lcd.cursor_pos = (1, 0)
        lcd.write_string(input_id)

        if len(input_id) == 5: # Verifikasi setelah 5 digit dimasukkan
            time.sleep(0.3)
            lcd.cursor_pos = (2, 0)
            lcd.write_string("Status:        ")
            if verify_tracking_id_from_db(input_id): # Panggil fungsi verifikasi DB
                lcd.cursor_pos = (2, 0)
                lcd.write_string("Status: Benar   ")
                indikator_benar()
                time.sleep(0.5)
                trigger_relay(relay_3, 3) # Asumsi relay 1 untuk loker kirim
                return 'menu_utama'
            else:
                lcd.cursor_pos = (2, 0)
                lcd.write_string("Status: Salah   ")
                indikator_salah()
                input_id = ""

def verify_otp_from_db(otp):
    conn = None
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cur = conn.cursor()
        # Query untuk memeriksa apakah OTP ada di tabel marketplace_transaction
        cur.execute(
            "SELECT 1 FROM marketplace_transaction WHERE otp = %s;",
            (otp,)
        )
        result = cur.fetchone()
        cur.close()
        return result is not None
    except Exception as e:
        print(f"Error connecting to or querying database for OTP: {e}")
        return False
    finally:
        if conn:
            conn.close()

def menu_ambil():
    lcd.clear()
    lcd.write_string("Masukkan 6 digit OTP")
    lcd.cursor_pos = (3, 0)
    lcd.write_string("#. Hapus  *. Kembali")
    input_id = ""

    while True:
        lcd.cursor_pos = (1, 0)
        lcd.write_string(" " * 16)
        lcd.cursor_pos = (1, 0)
        lcd.write_string(input_id)

        key = wait_key()

        if key == '*':
            return 'menu_utama'
        elif key == '#':
            input_id = ""
        elif key and len(input_id) < 6: # Batasi input menjadi 6 digit
            input_id += key

        lcd.cursor_pos = (1, 0)
        lcd.write_string(" " * 16)
        lcd.cursor_pos = (1, 0)
        lcd.write_string(input_id)

        if len(input_id) == 6: # Verifikasi setelah 6 digit dimasukkan
            time.sleep(0.3)
            lcd.cursor_pos = (2, 0)
            lcd.write_string("Status:        ")
            if verify_otp_from_db(input_id): # Panggil fungsi verifikasi OTP
                lcd.cursor_pos = (2, 0)
                lcd.write_string("Status: Benar   ")
                # Indikator benar dari fungsi lama
                lgpio.gpio_write(h, led_green, 0)
                lgpio.gpio_write(h, led_red, 1)
                lgpio.gpio_write(h, PIN_BUZZER, 1)
                time.sleep(0.8)
                lgpio.gpio_write(h, led_green, 1)
                lgpio.gpio_write(h, PIN_BUZZER, 0)
                time.sleep(0.5)
                trigger_relay(relay_1, 1) # Trigger relay 3 seperti di fungsi lama
                return 'menu_utama'
            else:
                lcd.cursor_pos = (2, 0)
                lcd.write_string("Status: Salah   ")
                # Indikator salah dari fungsi lama
                lgpio.gpio_write(h, led_green, 1)
                for _ in range(3):
                    lgpio.gpio_write(h, led_red, 0)
                    lgpio.gpio_write(h, PIN_BUZZER, 1)
                    time.sleep(0.2)
                    lgpio.gpio_write(h, led_red, 1)
                    lgpio.gpio_write(h, PIN_BUZZER, 0)
                    time.sleep(0.2)
                input_id = ""

# Main loop
# Mulai polling permintaan loker dari database
threading.Thread(target=poll_locker_requests, daemon=True).start()

# Mulai monitoring loadcell dengan toleransi
threading.Thread(target=monitor_loadcell, daemon=True).start()
print("Loadcell monitoring dimulai dengan toleransi 5 gram...")

# Inisialisasi MQTT client (jika masih diperlukan untuk fungsi lain)
setup_mqtt_client()
try:
    state = 'menu_utama'
    while True:
        if face_menu_requested and state != 'face_menu':
            face_menu_requested = False
            state = 'face_menu'

        if state == 'menu_utama':
            menu_utama()
            while True:
                if face_menu_requested:
                    break
                if cek_push_button():
                    break
                key = read_key()
                if key:
                    while read_key() is not None:
                        time.sleep(0.5)
                    if key == '1':
                        state = 'menu_kirim'
                    elif key == '2':
                        state = 'menu_ambil'
                    break
                time.sleep(0.05)

        elif state == 'menu_kirim':
            menu_kirim()
            key = wait_key()
            if key == '1':
                state = 'menu_scan_qr'
            elif key == '2':
                state = 'menu_input_id_kirim'
            elif key == '*':
                state = 'menu_utama'

        elif state == 'menu_scan_qr':
            state = menu_scan_qr()

        elif state == 'menu_input_id_kirim':
            state = menu_input_id('menu_kirim')

        elif state == 'menu_ambil':
            state = menu_ambil()

        elif state == 'face_menu':
            state = face_menu_loop()

except KeyboardInterrupt:
    lcd.clear()
    lgpio.gpio_write(h, PIN_RED, 1)
    lgpio.gpio_write(h, PIN_GREEN, 1)
    lgpio.gpiochip_close(h)
    lgpio.gpiochip_close(gpio_hcsr_handle)
    print("\nProgram dihentikan oleh pengguna. GPIO telah ditutup.")
