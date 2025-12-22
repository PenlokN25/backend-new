import requests
import cv2
import os
import sys
import tty
import termios
import time
import psycopg2
from psycopg2 import sql
from datetime import datetime

BASE_URL = "http://localhost:8000"
TEMP_DIR = "temp_images"

# Database config (match cobaface.py env/defaults)
DB_NAME = os.getenv("PG_DB", "smartlocker")
DB_USER = os.getenv("PG_USER", "smartlocker_admin")
DB_PASSWORD = os.getenv("PG_PASSWORD", "penlokjaya")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "1723")

os.makedirs(TEMP_DIR, exist_ok=True)


def getch():
    """Membaca single character tanpa perlu Enter"""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


def wait_for_asterisk():
    """Tunggu user menekan * untuk kembali"""
    print("\n* kembali ke menu...")
    while True:
        key = getch()
        if key == '*':
            break


def clear_screen():
    """Membersihkan layar terminal"""
    os.system('cls' if os.name == 'nt' else 'clear')


def check_user_images(username):
    """Cek apakah user sudah memiliki gambar training"""
    try:
        response = requests.get(
            f"{BASE_URL}/face/getuserimageexists/",
            params={"username": username}
        )
        return response.status_code, response.json()
    except Exception as e:
        print(f"Error: {truncate_text(str(e))}")
        return None, None


def cleanup_temp_files(username):
    """Membersihkan file temporary"""
    user_temp_dir = os.path.join(TEMP_DIR, username)
    if os.path.exists(user_temp_dir):
        for file in os.listdir(user_temp_dir):
            os.remove(os.path.join(user_temp_dir, file))
        os.rmdir(user_temp_dir)


def input_face_id():
    """Input Face ID menggunakan keypad numerik dengan konfirmasi # atau batal *"""
    print("\n" + "=" * 50)
    print("  INPUT FACE ID")
    print("=" * 50)
    print("\nMasukkan Face ID")
    print("# konfirmasi")
    print("* batal\n")
    print("Contoh: 626590\n")

    face_id = ""

    # Setup untuk membaca single key
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setraw(sys.stdin.fileno())

        while True:
            print(f"\rFace ID: {face_id}_", end='', flush=True)
            key = sys.stdin.read(1)

            if key == '*':
                print("\n⚠ Input dibatalkan")
                return None
            elif key == '#':
                if len(face_id) > 0:
                    print(f"\n✓ Face ID: {face_id}")
                    return face_id
                else:
                    print("\n✗ Face ID kosong!")
            elif key in '0123456789':
                face_id += key
            elif key == '\x7f':  # Backspace
                face_id = face_id[:-1]
            elif key == '\x1b':  # ESC
                print("\n⚠ Input dibatalkan")
                return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def get_user_by_faceid(face_id):
    """Mengambil data user berdasarkan Face ID langsung dari database"""
    conn = None
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
        )
        cur = conn.cursor()

        # DB schema menggunakan kolom face_id (lowercase); hindari query kolom tak ada
        face_col = sql.Identifier("face_id")
        query = sql.SQL(
            """
            SELECT username, first_name, last_name, role, {face_col}
            FROM users_user
            WHERE {face_col} = %s
            LIMIT 1
            """
        ).format(face_col=face_col)

        cur.execute(query, (face_id,))
        row = cur.fetchone()
        if row:
            username, first_name, last_name, role, face_value = row
            user_data = {
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "face_id": face_value,
                "role": role,
            }
            return 200, user_data

        return 404, None
    except Exception as e:
        print(f"Error DB: {truncate_text(str(e))}")
        return None, None
    finally:
        if conn:
            conn.close()


def load_face_cascade():
    """Load Haar Cascade dengan fallback"""
    # Coba load dari working directory
    face_cascade = cv2.CascadeClassifier('haarcascade_frontalface_default.xml')

    if face_cascade.empty():
        # Fallback ke cv2 data
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )

    if face_cascade.empty():
        raise Exception("Tidak load Cascade")

    return face_cascade


def verify_face_with_haar(image_path):
    """Verifikasi apakah ada wajah dalam gambar menggunakan Haar Cascade"""
    try:
        face_cascade = load_face_cascade()

        # Baca gambar
        img = cv2.imread(image_path)
        if img is None:
            return False

        # Convert ke grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Deteksi wajah
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

        return len(faces) > 0
    except Exception as e:
        print(f"Error: {truncate_text(str(e))}")
        return False


def auto_capture_images(username, num_images, show_overlay=True):
    """Mengambil gambar secara otomatis dan verifikasi wajah"""
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)

    if not cap.isOpened():
        print("❌ Kamera /dev/video0 tidak bisa dibuka")
        return []

    cv2.namedWindow('Auto Capture Images', cv2.WINDOW_NORMAL)

    # Load Haar Cascade
    face_cascade = load_face_cascade()

    verified_images = []
    user_temp_dir = os.path.join(TEMP_DIR, username)
    os.makedirs(user_temp_dir, exist_ok=True)

    print(f"\nMulai ambil {num_images} gambar")
    print(f"User: {truncate_text(username)}")
    print("Proses otomatis...")
    print("ESC: Batal\n")

    captured_count = 0
    frame_count = 0
    capture_interval = 30  # Ambil gambar setiap 30 frame (sekitar 1 detik)

    while len(verified_images) < num_images:
        ret, frame = cap.read()
        if not ret:
            print("Error: Baca frame")
            break

        frame_count += 1

        # Deteksi wajah untuk preview
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

        if show_overlay:
            # Gambar rectangle pada wajah yang terdeteksi
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # Tampilkan info
            cv2.putText(frame, f"OK: {len(verified_images)}/{num_images}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.putText(frame, f"Total: {captured_count}", (10, 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
            cv2.putText(frame, "ESC: Batal", (10, 110),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        cv2.imshow('Auto Capture Images', frame)

        # Ambil gambar otomatis setiap interval tertentu
        if frame_count >= capture_interval and len(faces) > 0:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{username}_{captured_count + 1}_{timestamp}.jpg"
            filepath = os.path.join(user_temp_dir, filename)

            cv2.imwrite(filepath, frame)
            captured_count += 1

            # Verifikasi wajah
            if verify_face_with_haar(filepath):
                verified_images.append(filepath)
                print(f"✓ Gambar {len(verified_images)} OK (Total: {captured_count})")
            else:
                os.remove(filepath)
                print(f"✗ Gambar {captured_count} gagal (OK: {len(verified_images)}/{num_images})")

            frame_count = 0  # Reset counter

        # Check untuk ESC key
        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            print("\n⚠ Dibatalkan")
            cap.release()
            cv2.destroyAllWindows()
            return []

    cap.release()
    cv2.destroyAllWindows()

    print(f"\n✓ Selesai! Total: {len(verified_images)}")
    return verified_images


def upload_images_to_server(username, image_paths):
    """Upload gambar ke server"""
    try:
        files = []
        for img_path in image_paths:
            files.append(
                ('image_list', (os.path.basename(img_path), open(img_path, 'rb'), 'image/jpeg'))
            )

        data = {'username': username}

        response = requests.post(
            f"{BASE_URL}/face/createimagetrainingusernew/",
            data=data,
            files=files
        )

        # Tutup semua file
        for _, (_, file_obj, _) in files:
            file_obj.close()

        return response.status_code, response.json()
    except Exception as e:
        print(f"Error: {truncate_text(str(e))}")
        return None, None


def input_number_images():
    """Input jumlah gambar menggunakan keypad dengan * lanjut, # kembali"""
    print("\nMasukkan jumlah gambar (0-9)")
    print("* lanjut")
    print("# kembali\n")

    num_str = ""

    # Setup untuk membaca single key
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setraw(sys.stdin.fileno())

        while True:
            print(f"\rJumlah: {num_str}_", end='', flush=True)
            key = sys.stdin.read(1)

            if key == '#':
                print("\n⚠ Kembali")
                return None, True  # None = tidak ada angka, True = kembali
            elif key == '*':
                if len(num_str) > 0 and int(num_str) > 0:
                    print(f"\n✓ Jumlah: {num_str}")
                    return int(num_str), False  # angka, False = lanjut
                else:
                    print("\n✗ Harus > 0!")
            elif key in '0123456789':
                num_str += key
            elif key == '\x7f':  # Backspace
                num_str = num_str[:-1]
            elif key == '\x1b':  # ESC
                print("\n⚠ Dibatalkan")
                return None, True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def process_user_training_by_faceid(username):
    """Proses training gambar untuk user berdasarkan username"""

    # Cek apakah user sudah punya gambar
    status_code, response = check_user_images(username)

    if status_code == 200:
        print("\n✓ Gambar ada!")
        print(f"Jumlah: {len(response['data'])}")
        print("\nProses tambah...")
        action_type = "tambahan"
    elif status_code == 403:
        print("\n⚠ Gambar tidak ada")
        action_type = "baru"
    else:
        print(f"\n✗ Error ({status_code})")
        wait_for_asterisk()
        return False

    # Input jumlah gambar dengan keypad
    while True:
        if action_type == "baru":
            print("\n--- JUMLAH GAMBAR BARU ---")
        else:
            print("\n--- JUMLAH GAMBAR TAMBAHAN ---")

        num_images, should_return = input_number_images()

        if should_return:  # User tekan # (kembali)
            return False

        if num_images is not None and num_images > 0:
            break
        else:
            print("Harus > 0!")

    # Proses pengambilan gambar otomatis dengan loop sampai cukup
    verified_images = []
    attempt = 1

    while len(verified_images) < num_images:
        remaining = num_images - len(verified_images)

        if attempt > 1:
            print(f"\n⚠ Kurang {remaining}")
            print(f"Coba ke-{attempt}...")
            time.sleep(2)

        print(f"\n--- Batch {attempt}: {remaining} ---")
        captured = auto_capture_images(username, remaining)

        if not captured:
            print("\n⚠ Dibatalkan")
            cleanup_temp_files(username)
            wait_for_asterisk()
            return False

        verified_images.extend(captured)
        attempt += 1

        # Batasi percobaan maksimal
        if attempt > 10:
            print("\n✗ Terlalu banyak coba")
            cleanup_temp_files(username)
            wait_for_asterisk()
            return False

    print(f"\n{'=' * 50}")
    print(f"✓ SUKSES! Total {len(verified_images)}")
    print(f"{'=' * 50}")

    # Upload ke server
    print("\n⏳ Upload...")
    status_code, response = upload_images_to_server(username, verified_images)

    if status_code == 200:
        print("\n" + "=" * 50)
        if action_type == "baru":
            print("✓ UPLOAD BERHASIL!")
        else:
            print("✓ TAMBAH BERHASIL!")
        print("=" * 50)
        msg = response.get('message', '')
        print(f"Msg: {truncate_text(msg)}")
        print(f"Jumlah: {len(response.get('data', []))}")
    else:
        print(f"\n✗ Gagal ({status_code})")
        print(f"Resp: {truncate_text(str(response))}")

    # Cleanup
    cleanup_temp_files(username)
    wait_for_asterisk()
    return True


def truncate_text(text, max_length=20):
    """Memotong teks jika lebih dari max_length"""
    if len(str(text)) > max_length:
        return str(text)[:max_length - 3] + "..."
    return str(text)


def print_header(title):
    """Menampilkan header menu"""
    print("\n" + "=" * 50)
    print(f"  {title}")
    print("=" * 50 + "\n")


def confirm_yes_no(message):
    """Konfirmasi dengan digit: 1=Ya, 2=Tidak"""
    print(f"\n{truncate_text(message, 40)}")
    print("1=Ya, 2=Tidak")

    while True:
        key = getch()
        if key == '1':
            print("✓ Ya")
            return True
        elif key == '2':
            print("✗ Tidak")
            return False


def menu_training_with_faceid():
    """Menu registrasi/tambah gambar training menggunakan Face ID"""
    clear_screen()
    print_header("REGIS/TAMBAH GAMBAR")

    # Input Face ID
    face_id = input_face_id()

    if not face_id:
        return

    # Get user data by Face ID
    print(f"\n⏳ Cari ID: {face_id}...")
    status_code, user_data = get_user_by_faceid(face_id)

    if status_code == 200 and user_data:
        print("\n✓ User ditemukan!")
        print("=" * 50)
        print(f"User : {truncate_text(user_data.get('username', 'N/A'))}")
        print(f"Email: {truncate_text(user_data.get('email', 'N/A'))}")
        fname = user_data.get('first_name', '')
        lname = user_data.get('last_name', '')
        fullname = f"{fname} {lname}".strip()
        print(f"Nama : {truncate_text(fullname) if fullname else 'N/A'}")
        print(f"ID   : {truncate_text(user_data.get('face_id', 'N/A'))}")
        print(f"Role : {truncate_text(user_data.get('role', 'N/A'))}")
        print("=" * 50)

        if confirm_yes_no("Lanjutkan training?"):
            username = user_data.get('username')
            if username:
                process_user_training_by_faceid(username)
            else:
                print("\n✗ Username tidak ada")
                wait_for_asterisk()
        else:
            print("\n⚠ Proses dibatalkan")
            wait_for_asterisk()

    elif status_code == 404:
        print(f"\n✗ ID '{face_id}' tidak ada!")
        print("Pastikan ID terdaftar")
        wait_for_asterisk()

    else:
        print(f"\n✗ Error ({status_code})")
        print("Cek server/koneksi")
        wait_for_asterisk()


def capture_single_image_with_verification(max_attempts=10):
    """Mengambil satu gambar dan verifikasi wajah dengan retry otomatis"""
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)

    if not cap.isOpened():
        print("❌ Kamera /dev/video0 tidak bisa dibuka")
        return None

    cv2.namedWindow('Face Verification', cv2.WINDOW_NORMAL)

    # Load Haar Cascade
    face_cascade = load_face_cascade()

    log_temp_dir = os.path.join(TEMP_DIR, "face_log")
    os.makedirs(log_temp_dir, exist_ok=True)

    print("\n⏳ Mulai ambil...")
    print("ESC: Batal\n")

    attempt = 0
    verified_image = None

    while attempt < max_attempts and verified_image is None:
        attempt += 1
        print(f"\n--- Coba ke-{attempt} ---")

        frame_count = 0
        capture_delay = 60  # Delay 60 frame (~2 detik) untuk stabilisasi

        while frame_count < capture_delay:
            ret, frame = cap.read()
            if not ret:
                print("Error: Baca frame")
                break

            frame_count += 1

            # Deteksi wajah untuk preview
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

            # Gambar rectangle pada wajah yang terdeteksi
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

            # Tampilkan info
            cv2.putText(frame, f"Try: {attempt}/{max_attempts}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, "Posisi tengah", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
            cv2.putText(frame, "ESC: Batal", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            cv2.imshow('Face Verification', frame)

            # Check untuk ESC key
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                print("\n⚠ Dibatalkan")
                cap.release()
                cv2.destroyAllWindows()
                return None

        # Ambil frame terakhir untuk capture
        ret, frame = cap.read()
        if not ret:
            print("Error: Baca capture")
            continue

        # Simpan gambar sementara
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"log_{timestamp}.jpg"
        filepath = os.path.join(log_temp_dir, filename)

        cv2.imwrite(filepath, frame)
        print(f"📸 Ambil: {truncate_text(filename)}")

        # Verifikasi wajah
        if verify_face_with_haar(filepath):
            verified_image = filepath
            print(f"✓ Wajah OK!")
        else:
            os.remove(filepath)
            print(f"✗ Wajah tidak ada")

            if attempt < max_attempts:
                print(f"⏳ Tunggu 2 detik...")
                time.sleep(2)

    cap.release()
    cv2.destroyAllWindows()

    if verified_image:
        print(f"\n✓ Berhasil!")
    else:
        print(f"\n✗ Gagal {max_attempts}x")

    return verified_image


def send_face_log_to_server(image_path):
    """Mengirim gambar face log ke server untuk verifikasi"""
    try:
        files = [
            ('image', (os.path.basename(image_path), open(image_path, 'rb'), 'image/jpeg'))
        ]

        print("\n⏳ Kirim ke server...")
        response = requests.post(
            f"{BASE_URL}/face/createlogusersmartnew/",
            files=files
        )

        # Tutup file
        files[0][1][1].close()

        return response.status_code, response.json()
    except Exception as e:
        print(f"Error: {truncate_text(str(e))}")
        return None, None


def cleanup_face_log_temp():
    """Membersihkan file temporary face log"""
    log_temp_dir = os.path.join(TEMP_DIR, "face_log")
    if os.path.exists(log_temp_dir):
        for file in os.listdir(log_temp_dir):
            file_path = os.path.join(log_temp_dir, file)
            try:
                os.remove(file_path)
            except Exception:
                print(f"Err del: {truncate_text(file)}")
        try:
            os.rmdir(log_temp_dir)
        except Exception:
            print("Err rmdir")


def process_face_log_verification():
    """Proses verifikasi wajah untuk log user"""
    clear_screen()
    print_header("VERIFIKASI WAJAH")

    print("Sistem ambil 1 foto")
    print("Posisi wajah jelas\n")

    print("* kembali")
    print("Tombol lain mulai")
    key = getch()
    if key == '*':
        return

    # Ambil gambar dengan verifikasi
    verified_image = capture_single_image_with_verification(max_attempts=10)

    if not verified_image:
        print("\n✗ Gagal/dibatalkan")
        cleanup_face_log_temp()
        wait_for_asterisk()
        return

    # Kirim ke server
    status_code, response = send_face_log_to_server(verified_image)

    if status_code == 200 and response:
        print("\n" + "=" * 60)
        print("✓ VERIFIKASI BERHASIL!")
        print("=" * 60)

        # Parse response
        result = response.get('result', [])
        confidence = response.get('confidence', 'N/A')

        if result and len(result) > 0:
            log_data = result[0]
            status = log_data.get('status', 'Unknown')
            log_id = log_data.get('log_id', 'N/A')
            id_face_user = log_data.get('id_face_user', 'N/A')
            access_time = log_data.get('access_time', 'N/A')

            print(f"\n📋 Detail:")
            print(f"   Status  : {truncate_text(status)}")
            print(f"   Conf    : {truncate_text(str(confidence))}")
            print(f"   User ID : {truncate_text(str(id_face_user))}")
            print(f"   Log ID  : {truncate_text(str(log_id))}")
            print(f"   Waktu   : {truncate_text(access_time)}")

            # Tampilkan status dengan warna
            if status.lower() == "authorized":
                print("\n" + "=" * 60)
                print("✅ AUTHORIZED")
                print("=" * 60)
            else:
                print("\n" + "=" * 60)
                print("❌ UNAUTHORIZED")
                print("=" * 60)

            # Jeda waktu sebelum kembali ke menu
            print("\n⏳ Kembali 5 detik...")
            time.sleep(5)
        else:
            print("\n⚠ Data tidak lengkap")
            wait_for_asterisk()
    else:
        print("\n" + "=" * 60)
        print(f"✗ VERIFIKASI GAGAL!")
        print("=" * 60)
        print(f"Status: {status_code}")
        print(f"Resp: {truncate_text(str(response))}")
        wait_for_asterisk()

    # Cleanup
    cleanup_face_log_temp()


def main_menu():
    """Menu utama aplikasi"""
    while True:
        clear_screen()
        print_header("FACE TRAINING")

        print("1. Regis/Tambah")
        print("2. Verifikasi")
        print("3. Keluar")
        print("\nPilih (1-3):")

        key = getch()

        if key == '1':
            menu_training_with_faceid()
        elif key == '2':
            process_face_log_verification()
        elif key == '3':
            print("\nSelesai!")
            break
        else:
            print("\n✗ Pilihan invalid!")
            time.sleep(1)


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\nDihentikan")
    finally:
        # Cleanup
        if os.path.exists(TEMP_DIR):
            for item in os.listdir(TEMP_DIR):
                item_path = os.path.join(TEMP_DIR, item)
                if os.path.isdir(item_path):
                    try:
                        for file in os.listdir(item_path):
                            os.remove(os.path.join(item_path, file))
                        os.rmdir(item_path)
                    except Exception:
                        print(f"Err: {truncate_text(item)}")
