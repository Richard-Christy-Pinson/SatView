from flask import Flask, request, render_template
from skyfield.api import Loader, Topos
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import os
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
import ee
import folium
import logging

# Initialize Google Earth Engine (make sure authentication is done)
# ee.Initialize()

app = Flask(__name__)

# Initialize the scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# Load environment variables from .env file
load_dotenv()

# Function to calculate the next satellite pass times
def get_next_pass_times(latitude, longitude):
    load = Loader('./data')
    ts = load.timescale()
    satellites = load.tle_file('https://celestrak.org/NORAD/elements/resource.txt')
    location = Topos(latitude_degrees=latitude, longitude_degrees=longitude)

    next_passes = []
    for satellite in satellites:
        t0 = ts.now()
        t1 = ts.utc(t0.utc_datetime() + timedelta(days=2))
        times, events = satellite.find_events(location, t0, t1, altitude_degrees=30.0)
        for ti, event in zip(times, events):
            if event == 0:
                pass_time = ti.utc_datetime()
                next_passes.append((satellite.name, pass_time.strftime('%Y-%m-%d %H:%M:%S')))
                break
    return next_passes

# Function to estimate data availability
def estimate_data_availability(pass_time_str):
    pass_time = datetime.strptime(pass_time_str, '%Y-%m-%d %H:%M:%S')
    return (pass_time + timedelta(hours=6)).strftime('%Y-%m-%d %H:%M:%S')

# Function to send confirmation email
def send_confirmation_email(user_id):
    sender_email = os.getenv('SENDER_EMAIL')
    sender_password = os.getenv('SENDER_PASSWORD')
    message = "Thank you for your request! We will notify you when the satellite passes over your location."
    msg = MIMEText(message)
    msg['Subject'] = 'Confirmation: Satellite Pass Notification Request Received'
    msg['From'] = sender_email
    msg['To'] = user_id
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, user_id, msg.as_string())
    except Exception as e:
        print(f"Failed to send confirmation email: {e}")

# Function to send notification via email
def send_notification(user_id, message):
    sender_email = os.getenv('SENDER_EMAIL')
    sender_password = os.getenv('SENDER_PASSWORD')
    msg = MIMEText(message)
    msg['Subject'] = 'Satellite Pass Notification'
    msg['From'] = sender_email
    msg['To'] = user_id
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, user_id, msg.as_string())
    except Exception as e:
        print(f"Failed to send notification: {e}")

# Function to schedule a notification
def schedule_notification(notification_time_str, user_id, message):
    notification_time = datetime.strptime(notification_time_str, '%Y-%m-%d %H:%M:%S')
    scheduler.add_job(func=send_notification,
                      trigger='date',
                      run_date=notification_time,
                      args=[user_id, message],
                      misfire_grace_time=3600)

# Function to display the 3x3 grid of Landsat pixels
def display_grid_on_map(latitude, longitude):
    # Center the map on the location
    m = folium.Map(location=[latitude, longitude], zoom_start=12)

    # Define the central pixel and surrounding pixels (approx. 30m Landsat resolution)
    offset = 0.00027  # Approx 30m in degrees (can adjust based on actual resolution)
    for i in range(-1, 2):
        for j in range(-1, 2):
            folium.Rectangle(
                bounds=[
                    [latitude + i * offset, longitude + j * offset],
                    [latitude + (i + 1) * offset, longitude + (j + 1) * offset]
                ],
                color='blue',
                fill=True,
                fill_opacity=0.3
            ).add_to(m)

    # Add a marker for the center point
    folium.Marker([latitude, longitude], popup="Center").add_to(m)

    # Save the map in the static folder
    map_path = 'static/map.html'
    m.save(map_path)
    print(f"Map saved at {map_path}")  # Debug print

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        try:
            latitude = float(request.form['latitude'])
            longitude = float(request.form['longitude'])
            notification_time = int(request.form['notification_time'])
            user_id = request.form['user_id']

            send_confirmation_email(user_id)

            # Get all satellite passes
            next_passes = get_next_pass_times(latitude, longitude)
            scheduled_notifications = []
            data_availabilities = []

            now = datetime.utcnow()
            for satellite_name, pass_time_str in next_passes:
                satellite_name_normalized = satellite_name.strip().upper()
                if "LANDSAT 8" in satellite_name_normalized or "LANDSAT 9" in satellite_name_normalized:
                    pass_time = datetime.strptime(pass_time_str, '%Y-%m-%d %H:%M:%S')
                    notify_time = pass_time - timedelta(minutes=notification_time)

                    if notify_time > now:
                        notify_time_str = notify_time.strftime('%Y-%m-%d %H:%M:%S')
                        message = f"{satellite_name} will pass over your location at {pass_time_str} UTC"
                        schedule_notification(notify_time_str, user_id, message)
                        scheduled_notifications.append((satellite_name, notify_time_str))
                        data_availability_str = estimate_data_availability(pass_time_str)
                        data_availabilities.append((satellite_name, data_availability_str))

            if not scheduled_notifications:
                return render_template('error.html', error_message='No future satellite passes found within the next 48 hours for Landsat 8 or 9.')

            # Display the 3x3 grid of pixels on the map
            display_grid_on_map(latitude, longitude)

            return render_template('confirmation.html',
                                   next_passes=scheduled_notifications,
                                   scheduled_notifications=scheduled_notifications,
                                   data_availabilities=data_availabilities,
                                   user_id=user_id,
                                   map_created=True)
        except Exception as e:
            print(f"Error occurred: {e}")
            return render_template('error.html', error_message=str(e))
    return render_template('home.html', map_created=False)

@app.route('/map')
def map():
    return app.send_static_file('map.html')

def initialize_earth_engine():
    try:
        ee.Initialize()
        logging.info("Earth Engine initialized successfully.")
        return True
    except ee.EEException as e:
        logging.error(f"Error initializing Earth Engine: {e}")
        return False

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True)
