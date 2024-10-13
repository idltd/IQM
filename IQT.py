import speedtest
import time
import logging
from flask import Flask, render_template, request, jsonify, abort
import sqlite3
import threading
import traceback
import subprocess
import json

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration (you can extend this to be loaded from a file or environment variables)
CONFIG = {
    'test_interval': 3600,  # 1 hour
    'ping_target': 'google.com',
    'test_mode': False
}

# Database setup
def get_db_connection():
    conn = sqlite3.connect('speedtest.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS speedtests
                        (timestamp INTEGER, download REAL, upload REAL, ping REAL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS outages
                        (start_time INTEGER, end_time INTEGER)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS logs
                        (timestamp INTEGER, level TEXT, message TEXT)''')
        conn.commit()
    logger.info("Database initialized")

init_db()

# Speed test function
def run_speed_test():
    try:
        logger.info("Starting speed test")
        st = speedtest.Speedtest()
        st.get_best_server()
        download_speed = st.download() / 1_000_000  # Convert to Mbps
        upload_speed = st.upload() / 1_000_000  # Convert to Mbps
        ping = st.results.ping
        
        with get_db_connection() as conn:
            conn.execute("INSERT INTO speedtests VALUES (?, ?, ?, ?)",
                         (int(time.time()), download_speed, upload_speed, ping))
            conn.commit()
        logger.info(f"Speed test completed: Download: {download_speed:.2f} Mbps, Upload: {upload_speed:.2f} Mbps, Ping: {ping:.2f} ms")
        return True
    except Exception as e:
        logger.error(f"Speed test failed: {str(e)}")
        return False

# Outage detection
def check_connection():
    if not run_speed_test():
        start_time = int(time.time())
        logger.warning(f"Outage detected at {start_time}")
        while not run_speed_test():
            time.sleep(60)  # Check every minute
        end_time = int(time.time())
        with get_db_connection() as conn:
            conn.execute("INSERT INTO outages VALUES (?, ?)", (start_time, end_time))
            conn.commit()
        logger.info(f"Outage ended at {end_time}")

# Scheduler
def scheduler():
    while True:
        run_speed_test()
        check_connection()
        time.sleep(CONFIG['test_interval'])

# Start scheduler in a separate thread
scheduler_thread = threading.Thread(target=scheduler, daemon=True)
scheduler_thread.start()

# Utility functions
def ping(host):
    try:
        output = subprocess.check_output(["ping", "-c", "4", host]).decode()
        return output
    except subprocess.CalledProcessError:
        return "Ping failed"

def traceroute(host):
    try:
        output = subprocess.check_output(["traceroute", host]).decode()
        return output
    except subprocess.CalledProcessError:
        return "Traceroute failed"

# Web interface routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/speedtests')
def get_speedtests():
    with get_db_connection() as conn:
        speedtests = conn.execute("SELECT * FROM speedtests ORDER BY timestamp DESC LIMIT 100").fetchall()
    return jsonify([dict(ix) for ix in speedtests])

@app.route('/outages')
def get_outages():
    with get_db_connection() as conn:
        outages = conn.execute("SELECT * FROM outages ORDER BY start_time DESC LIMIT 50").fetchall()
    return jsonify([dict(ix) for ix in outages])

@app.route('/debug')
def debug():
    app_status = {
        'app_running': True,
        'scheduler_running': scheduler_thread.is_alive(),
        'test_mode': CONFIG['test_mode'],
        'last_speed_test': get_last_speed_test(),
        'database_status': check_database_status(),
        'config': CONFIG
    }
    return render_template('debug.html', status=app_status)

@app.route('/logs')
def get_logs():
    with get_db_connection() as conn:
        logs = conn.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 100").fetchall()
    return jsonify([dict(ix) for ix in logs])

@app.route('/manual_test', methods=['POST'])
def manual_test():
    success = run_speed_test()
    return jsonify({'success': success})

@app.route('/ping', methods=['POST'])
def run_ping():
    host = request.json.get('host', CONFIG['ping_target'])
    result = ping(host)
    return jsonify({'result': result})

@app.route('/traceroute', methods=['POST'])
def run_traceroute():
    host = request.json.get('host', CONFIG['ping_target'])
    result = traceroute(host)
    return jsonify({'result': result})

@app.route('/config', methods=['GET', 'POST'])
def config():
    if request.method == 'POST':
        new_config = request.json
        # Validate and update configuration
        if 'test_interval' in new_config:
            CONFIG['test_interval'] = int(new_config['test_interval'])
        if 'ping_target' in new_config:
            CONFIG['ping_target'] = new_config['ping_target']
        if 'test_mode' in new_config:
            CONFIG['test_mode'] = bool(new_config['test_mode'])
        return jsonify({'status': 'Configuration updated', 'config': CONFIG})
    return jsonify(CONFIG)

def get_last_speed_test():
    with get_db_connection() as conn:
        last_test = conn.execute("SELECT * FROM speedtests ORDER BY timestamp DESC LIMIT 1").fetchone()
    return dict(last_test) if last_test else None

def check_database_status():
    try:
        with get_db_connection() as conn:
            conn.execute("SELECT 1")
        return "Connected"
    except Exception as e:
        return f"Error: {str(e)}"

@app.errorhandler(Exception)
def handle_error(e):
    logger.error(f"An error occurred: {str(e)}")
    logger.error(traceback.format_exc())
    return jsonify(error=str(e), stacktrace=traceback.format_exc()), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)