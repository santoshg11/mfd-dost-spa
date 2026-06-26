import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

app = Flask(__name__)

# SMTP Configuration
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

# Admin/Contact Details
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_MOBILE = os.environ.get("ADMIN_MOBILE", "")
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", ADMIN_MOBILE)
TELEGRAM_USERNAME = os.environ.get("TELEGRAM_USERNAME", "Keenlearnerujjwal")

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

def get_todays_file():
    today = datetime.now().strftime('%Y_%m_%d')
    return os.path.join(DATA_DIR, f'contacts_{today}.json')

def get_contacts(filepath):
    if not os.path.exists(filepath):
        return []
    with open(filepath, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_contact(contact_data):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    
    filepath = get_todays_file()
    contacts = get_contacts(filepath)
    
    contact_data['timestamp'] = datetime.now().isoformat()
    contact_data['processed'] = False
    
    contacts.append(contact_data)
    with open(filepath, 'w') as f:
        json.dump(contacts, f, indent=4)

def send_email(to_email, subject, body):
    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        # Only login if credentials are provided
        if SMTP_USER and SMTP_PASS:
            server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        return True, "Email sent successfully"
    except Exception as e:
        print(f"SMTP Error: {str(e)}")
        return False, str(e)

def log_to_failed_file(contact_data, error_msg):
    today = datetime.now().strftime('%Y_%m_%d')
    failed_filepath = os.path.join(DATA_DIR, f'contacts_{today}_failed.json')
    
    failed_data = []
    if os.path.exists(failed_filepath):
        try:
            with open(failed_filepath, 'r') as f:
                failed_data = json.load(f)
        except json.JSONDecodeError:
            pass
            
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "error": error_msg,
        "contact_data": contact_data
    }
    failed_data.append(log_entry)
    
    with open(failed_filepath, 'w') as f:
        json.dump(failed_data, f, indent=4)

def do_process_contacts(is_retry=False):
    job_type = "Retry job" if is_retry else "Daily job"
    print(f"[{datetime.now()}] Running {job_type} to process contacts...")
    filepath = get_todays_file()
    contacts = get_contacts(filepath)
    
    if not contacts:
        return

    base_dir = os.path.dirname(__file__)
    try:
        with open(os.path.join(base_dir, 'templates/admin_notification.txt'), 'r') as f:
            admin_template = f.read()
        with open(os.path.join(base_dir, 'templates/user_welcome.txt'), 'r') as f:
            user_template = f.read()
    except Exception as e:
        print(f"Error loading templates: {e}")
        return

    updated_contacts = []
    changes_made = False
    
    for contact in contacts:
        if contact.get('processed'):
            updated_contacts.append(contact)
            continue
            
        retry_count = contact.get('retry_count', 0)
        
        if is_retry:
            # Retry job only processes failed contacts that haven't reached max retries (3)
            if retry_count == 0 or retry_count >= 3:
                updated_contacts.append(contact)
                continue
        else:
            # Daily job only processes new contacts
            if retry_count > 0:
                updated_contacts.append(contact)
                continue

        changes_made = True
        name = contact.get('name', 'User')
        email = contact.get('email', 'unknown')
        mobile = contact.get('mobile', '')
        business = contact.get('business', '')
        message = contact.get('message', '')

        admin_body = admin_template.format(name=name, email=email, mobile=mobile, business=business, message=message)
        user_body = user_template.format(name=name)

        admin_sent = contact.get('admin_email_sent', False)
        user_sent = contact.get('user_email_sent', False)
        
        errors = []

        # 1. Send Admin Email
        if not admin_sent:
            print(f"Processing Admin Email to {ADMIN_EMAIL}")
            success_admin, err_admin = send_email(ADMIN_EMAIL, f"New Contact: {name}", admin_body)
            if success_admin:
                contact['admin_email_sent'] = True
            else:
                errors.append(f"Admin Email Failed: {err_admin}")

        # 2. Send User Email
        if not user_sent and email and email != 'unknown':
            print(f"Processing User Welcome Email to {email}")
            success_user, err_user = send_email(email, "Welcome to MFD-DOST - We have received your details!", user_body)
            if success_user:
                contact['user_email_sent'] = True
            else:
                errors.append(f"User Email Failed: {err_user}")
        elif email == 'unknown' or not email:
            contact['user_email_sent'] = True

        # 3. Trigger Mock SMS
        if not contact.get('sms_sent', False):
            print(f"[MSG_SERVICE] Sending SMS to ADMIN: {ADMIN_MOBILE}")
            print(f"[MSG_SERVICE] Content: New lead: {name} has contacted you via the website.")
            contact['sms_sent'] = True
            
        if not errors:
            contact['processed'] = True
        else:
            contact['retry_count'] = retry_count + 1
            error_msg = "; ".join(errors)
            log_to_failed_file(contact, error_msg)
            
        updated_contacts.append(contact)

    if changes_made:
        with open(filepath, 'w') as f:
            json.dump(updated_contacts, f, indent=4)
        print(f"[{datetime.now()}] {job_type} completed. Changes saved.")

# Scheduler setup
scheduler = BackgroundScheduler()
# Run everyday at 18:00 (6:00 PM) for initial processing
scheduler.add_job(func=lambda: do_process_contacts(is_retry=False), trigger="cron", hour=18, minute=0)
# Run every 15 minutes to retry failed attempts (up to 3 times)
scheduler.add_job(func=lambda: do_process_contacts(is_retry=True), trigger="interval", minutes=15)
scheduler.start()

# Flask Routes
@app.route('/')
def index():
    whatsapp_clean = WHATSAPP_NUMBER.replace('+', '').replace(' ', '').replace('-', '')
    telegram_clean = TELEGRAM_USERNAME.replace('@', '')
    return render_template('index.html', whatsapp_number=whatsapp_clean, telegram_username=telegram_clean)

@app.route('/api/contact', methods=['POST'])
def contact():
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()

    if not data or not data.get('name') or not data.get('email'):
        return jsonify({"success": False, "message": "Name and Email are required."}), 400

    # Save to JSON
    save_contact(data)
    
    return jsonify({"success": True, "message": "Your message has been received."}), 200

@app.route('/api/trigger-batch', methods=['GET', 'POST'])
def trigger_batch():
    # Only allow trigger if a matching token is provided, protecting the deployed app
    token = request.args.get('token')
    
    # Strictly require a token from the environment (.env or Heroku Config Vars)
    expected_token = os.environ.get("ADMIN_TOKEN")
    
    # Block access if no token is configured in the environment or if it doesn't match
    if not expected_token or token != expected_token:
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    # Manual bypass to immediately process pending contacts
    do_process_contacts(is_retry=False) # Run the 6 PM daily job logic
    do_process_contacts(is_retry=True)  # Run the 15-min retry job logic
    return jsonify({"success": True, "message": "Batch processes triggered manually. Check terminal logs."}), 200

if __name__ == '__main__':
    # When running with debug=True, the scheduler might start twice due to the reloader.
    app.run(host='0.0.0.0', debug=True, port=8000, use_reloader=False)
