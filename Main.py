from flask import Flask, request, redirect, url_for, render_template_string, session, jsonify, flash, g
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, logging, json
from functools import wraps
from math import radians, sin, cos, sqrt, atan2
import urllib.parse
from datetime import datetime

# ----------------------------
# App configuration
# ----------------------------
app = Flask(__name__)
app.secret_key = "school_bus_tracker_secret"
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), "uploads")
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024  # 4 MB
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(os.path.abspath(os.path.dirname(__file__)), "static"), exist_ok=True)

DB = os.path.join(os.path.abspath(os.path.dirname(__file__)), "bus.db")
DEFAULT_PROFILE_IMG = "static/default_profile.png"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

# ----------------------------
# Constants for a simplified demo
# ----------------------------
SCHOOL_LOCATION = {'lat': 28.6139, 'lon': 77.2090} # New Delhi
AVERAGE_BUS_SPEED_KMPH = 30 
BUS_NEAR_DISTANCE_KM = 0.5 # 500 meters for notification

# ----------------------------
# HTML Templates (with Bootstrap 5)
# ----------------------------
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>School Bus Tracker™</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    {% block head %}{% endblock %}
    <style>
        body { background-color: #f4f4f9; }
        .container { background-color: #fff; padding: 2rem; border-radius: 1rem; box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1); margin-top: 2rem; }
        .btn-custom { border-radius: 50px; padding: 10px 20px; }
        .profile-img { width: 120px; height: 120px; border-radius: 50%; object-fit: cover; border: 4px solid #007bff; }
        #mapid { height: 400px; margin-top: 20px; border-radius: 10px; }
        .card { border-radius: 15px; }
        .footer { text-align: center; margin-top: 30px; color: #888; font-size: 14px; }
        .nav-link.active { font-weight: bold; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="{{ url_for('home') }}">🚌 Tracker</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav" aria-controls="navbarNav" aria-expanded="false" aria-label="Toggle navigation">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav me-auto mb-2 mb-lg-0">
                    <li class="nav-item">
                        <a class="nav-link {% if request.path == url_for('home') %}active{% endif %}" href="{{ url_for('home') }}">Home</a>
                    </li>
                    {% if session.get('role') == 'parents' %}
                    <li class="nav-item">
                        <a class="nav-link {% if request.path == url_for('parent_dashboard') %}active{% endif %}" href="{{ url_for('parent_dashboard') }}">Dashboard</a>
                    </li>
                    {% elif session.get('role') == 'drivers' %}
                    <li class="nav-item">
                        <a class="nav-link {% if request.path == url_for('driver_dashboard') %}active{% endif %}" href="{{ url_for('driver_dashboard') }}">Dashboard</a>
                    </li>
                    {% elif session.get('role') == 'admin' %}
                    <li class="nav-item">
                        <a class="nav-link {% if request.path == url_for('admin_dashboard') %}active{% endif %}" href="{{ url_for('admin_dashboard') }}">Admin</a>
                    </li>
                    {% endif %}
                </ul>
                <div class="d-flex">
                    {% if session.get('user_id') %}
                        <a href="{{ url_for('logout') }}" class="btn btn-outline-light btn-sm">Logout</a>
                    {% else %}
                        <a href="{{ url_for('login', role='parent') }}" class="btn btn-outline-light btn-sm me-2">Parent Login</a>
                        <a href="{{ url_for('login', role='driver') }}" class="btn btn-outline-light btn-sm">Driver Login</a>
                    {% endif %}
                </div>
            </div>
        </div>
    </nav>
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                {{ message }}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

HOME_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<div class="text-center">
    <h1 class="mb-4">🚌 School Bus Tracker™</h1>
    <a href="{{ url_for('login', role='parent') }}" class="btn btn-primary btn-custom mx-2 mb-2">Parent Login</a>
    <a href="{{ url_for('login', role='driver') }}" class="btn btn-success btn-custom mx-2 mb-2">Driver Login</a>
    <a href="{{ url_for('admin_login') }}" class="btn btn-danger btn-custom mx-2 mb-2">Admin Login</a>
    <hr class="my-4">
    <p class="mb-0">New to the app? Register here:</p>
    <a href="{{ url_for('register', role='parent') }}" class="btn btn-link">Parent Register</a> | 
    <a href="{{ url_for('register', role='driver') }}" class="btn btn-link">Driver Register</a>
</div>
""")

LOGIN_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<h2 class="text-center">{{ role.title() }} Login</h2>
<form method="post" class="mt-4">
    <div class="mb-3">
        <label for="username" class="form-label">Username</label>
        <input type="text" class="form-control" id="username" name="username" required>
    </div>
    <div class="mb-3">
        <label for="password" class="form-label">Password</label>
        <input type="password" class="form-control" id="password" name="password" required>
    </div>
    <button type="submit" class="btn btn-primary w-100 btn-custom">{{ role.title() }} Login</button>
</form>
<div class="text-center mt-3">
    <a href="{{ url_for('home') }}">Back to Home</a>
</div>
""")

REGISTER_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<h2 class="text-center">Register as {{ role.title() }}</h2>
<form method="post" enctype="multipart/form-data" class="mt-4">
    <div class="mb-3">
        <label for="name" class="form-label">Full Name</label>
        <input type="text" class="form-control" id="name" name="name" required>
    </div>
    <div class="mb-3">
        <label for="username" class="form-label">Username</label>
        <input type="text" class="form-control" id="username" name="username" required>
    </div>
    <div class="mb-3">
        <label for="password" class="form-label">Password</label>
        <input type="password" class="form-control" id="password" name="password" required>
    </div>
    <div class="mb-3">
        <label for="phone" class="form-label">Phone Number</label>
        <input type="tel" class="form-control" id="phone" name="phone" placeholder="e.g., +919876543210" required>
    </div>
    <div class="mb-3">
        <label for="photo" class="form-label">Profile Photo (optional)</label>
        <input type="file" class="form-control" id="photo" name="photo" accept="image/*">
    </div>
    <button type="submit" class="btn btn-primary w-100 btn-custom">Register</button>
</form>
<div class="text-center mt-3">
    <p class="mb-0">Already have an account? <a href="{{ url_for('login', role=role) }}">Login</a></p>
</div>
""")

EDIT_PROFILE_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<h2 class="text-center">Edit Profile</h2>
<form method="post" enctype="multipart/form-data" class="mt-4">
    <div class="text-center mb-4">
        <img src="{{ photo_url }}" class="profile-img" alt="Current Photo">
    </div>
    <div class="mb-3">
        <label for="name" class="form-label">Full Name</label>
        <input type="text" class="form-control" id="name" name="name" value="{{ user.name }}" required>
    </div>
    <div class="mb-3">
        <label for="phone" class="form-label">Phone Number</label>
        <input type="tel" class="form-control" id="phone" name="phone" value="{{ user.phone }}" required>
    </div>
    <div class="mb-3">
        <label for="photo" class="form-label">Update Profile Photo (optional)</label>
        <input type="file" class="form-control" id="photo" name="photo" accept="image/*">
    </div>
    <button type="submit" class="btn btn-primary w-100 btn-custom">Update Profile</button>
</form>
<div class="text-center mt-3">
    <a href="{{ url_for(session.role + '_dashboard') }}">Back to Dashboard</a>
</div>
""")

PARENT_DASHBOARD_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<h2 class="text-center">Parent Dashboard</h2>
<div class="text-center my-4">
    <img src="{{ photo_url }}" class="profile-img" alt="Profile Photo">
    <h4 class="mt-3">{{ user.name }}</h4>
    <p class="text-muted">Phone: {{ user.phone }}</p>
</div>
<div class="row">
    <div class="col-md-6 mb-4">
        <div class="card bg-light">
            <div class="card-body">
                <h5 class="card-title">My Children</h5>
                <ul class="list-group list-group-flush">
                {% for child in children %}
                    <li class="list-group-item">{{ child.name }} (Class {{ child.class_name }})<br>
                    <small>Bus: {{ child.driver_name }}'s Bus</small>
                    </li>
                {% else %}
                    <li class="list-group-item text-muted">No children added yet.</li>
                {% endfor %}
                </ul>
                <a href="{{ url_for('add_child') }}" class="btn btn-secondary btn-sm mt-3">Add Child</a>
            </div>
        </div>
    </div>
    <div class="col-md-6 mb-4">
        <div class="card bg-light">
            <div class="card-body">
                <h5 class="card-title">Bus Tracking</h5>
                <div class="d-grid gap-2">
                    <a href="{{ url_for('bus_map') }}" class="btn btn-primary btn-custom">Track Bus Live</a>
                    <a href="{{ url_for('edit_profile') }}" class="btn btn-outline-secondary btn-custom">Edit Profile</a>
                </div>
            </div>
        </div>
    </div>
</div>
<div class="card mt-4">
    <div class="card-body">
        <h5 class="card-title">Complaints & Feedback</h5>
        <p>Leave feedback or submit a complaint about the driver or service.</p>
        <a href="{{ url_for('feedback') }}" class="btn btn-success btn-custom">Give Feedback / Rate Driver</a>
        <a href="{{ url_for('submit_complaint') }}" class="btn btn-warning btn-custom">Submit Complaint</a>
    </div>
</div>
""")

DRIVER_DASHBOARD_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<h2 class="text-center">Driver Dashboard</h2>
<div class="text-center my-4">
    <img src="{{ photo_url }}" class="profile-img" alt="Profile Photo">
    <h4 class="mt-3">{{ user.name }}</h4>
    <p class="text-muted">Phone: {{ user.phone }}</p>
    {% if rating %}
    <p>Average Rating: <strong>{{ "%.1f" | format(rating) }} / 5</strong> (from {{ total_ratings }} ratings)</p>
    {% else %}
    <p class="text-muted">No ratings yet.</p>
    {% endif %}
</div>
<div class="card mt-4">
    <div class="card-body">
        <h5 class="card-title">Location Update</h5>
        <p class="text-muted">Current Location: <span id="lat">N/A</span>, <span id="lon">N/A</span></p>
        <div class="d-grid gap-2">
            <button class="btn btn-primary btn-custom" id="updateLocationBtn">Update My Location</button>
            <a href="{{ url_for('edit_profile') }}" class="btn btn-outline-secondary btn-custom">Edit Profile</a>
        </div>
    </div>
</div>
<div class="card mt-4">
    <div class="card-body">
        <h5 class="card-title">Notify Parents</h5>
        <p>Click to send a WhatsApp message to the parent for each student when you arrive at their stop.</p>
        <ul class="list-group">
        {% for child in children %}
            <li class="list-group-item d-flex justify-content-between align-items-center">
                {{ child.child_name }}
                <a href="{{ child.wa_link }}" target="_blank" class="btn btn-success btn-sm">Notify on WhatsApp</a>
            </li>
        {% else %}
            <li class="list-group-item text-muted">No children assigned.</li>
        {% endfor %}
        </ul>
    </div>
</div>

<script>
    const updateBtn = document.getElementById('updateLocationBtn');
    updateBtn.addEventListener('click', () => {
        updateBtn.disabled = true;
        updateBtn.innerText = 'Getting location...';

        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(position => {
                const lat = position.coords.latitude;
                const lon = position.coords.longitude;
                document.getElementById('lat').innerText = lat.toFixed(6);
                document.getElementById('lon').innerText = lon.toFixed(6);

                fetch('{{ url_for("update_location") }}', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ lat: lat, lon: lon })
                })
                .then(response => response.json())
                .then(data => {
                    alert(data.message);
                    updateBtn.disabled = false;
                    updateBtn.innerText = 'Update My Location';
                })
                .catch(error => {
                    alert('Error updating location: ' + error);
                    updateBtn.disabled = false;
                    updateBtn.innerText = 'Update My Location';
                });
            }, error => {
                alert('Geolocation error: ' + error.message);
                updateBtn.disabled = false;
                updateBtn.innerText = 'Update My Location';
            });
        } else {
            alert("Geolocation is not supported by this browser.");
            updateBtn.disabled = false;
            updateBtn.innerText = 'Update My Location';
        }
    });
</script>
""")

BUS_MAP_TEMPLATE = BASE_TEMPLATE.replace("{% block head %}{% endblock %}", """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
""").replace("{% block content %}{% endblock %}", """
<h2 class="text-center">Live Bus Map</h2>
<div id="mapid" class="card"></div>
<div class="d-grid gap-2 mt-3">
    {% for driver in drivers %}
        <button class="btn btn-outline-primary" onclick="centerMap({{ driver.lat }}, {{ driver.lon }})">Follow {{ driver.name }}'s Bus</button>
    {% endfor %}
</div>
<p class="text-center mt-3"><a href="{{ url_for('parent_dashboard') }}">Back to Dashboard</a></p>

<script>
    var map = L.map('mapid').setView([20.5937, 78.9629], 5); // Center on India

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    var busMarkers = {};
    var schoolMarker = L.marker([{{ school_lat }}, {{ school_lon }}], {icon: L.divIcon({className: 'school-icon', html: '<div style="background-color:red;width:20px;height:20px;border-radius:50%;"></div>'})}).addTo(map);
    schoolMarker.bindPopup("<b>School</b>").openPopup();

    function centerMap(lat, lon) {
        map.setView([lat, lon], 13);
    }
    
    function haversine_distance(coords1, coords2) {
        function toRad(x) { return x * Math.PI / 180; }
        var lon1 = coords1.lon;
        var lat1 = coords1.lat;
        var lon2 = coords2.lon;
        var lat2 = coords2.lat;
        var R = 6371; // km
        var dLat = toRad(lat2 - lat1);
        var dLon = toRad(lon2 - lon1);
        var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
                Math.sin(dLon / 2) * Math.sin(dLon / 2);
        var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return R * c;
    }

    var lastAlertTime = 0;
    var alertedDrivers = {};

    function updateBusLocationsAndCheckAlerts() {
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(position => {
                var parentCoords = { lat: position.coords.latitude, lon: position.coords.longitude };
                fetch('{{ url_for("bus_locations") }}')
                    .then(response => response.json())
                    .then(data => {
                        data.drivers.forEach(driver => {
                            var lat = driver.lat;
                            var lon = driver.lon;

                            if (lat && lon) {
                                var driverId = driver.id;
                                var driverName = driver.name;
                                var driverPhoto = driver.photo;
                                var driverRating = driver.rating;
                                var driverPhone = driver.phone;
                                var eta = driver.eta;
                                var lastUpdated = driver.last_updated;

                                var popupContent = `<b>${driverName}'s Bus</b><br>
                                                    Phone: ${driverPhone}<br>
                                                    Rating: ${driverRating ? driverRating.toFixed(1) + ' / 5' : 'No ratings'}<br>
                                                    ETA: ${eta}<br>
                                                    Last Updated: ${lastUpdated}`;
                                
                                if (busMarkers[driverId]) {
                                    busMarkers[driverId].setLatLng([lat, lon]).setPopupContent(popupContent);
                                } else {
                                    var busIcon = L.divIcon({
                                        className: 'bus-icon',
                                        html: '<img src="' + driverPhoto + '" style="width:40px;height:40px;border-radius:50%;border:3px solid #007bff;"/>',
                                        iconSize: [40, 40],
                                    });
                                    var marker = L.marker([lat, lon], {icon: busIcon}).addTo(map);
                                    marker.bindPopup(popupContent);
                                    busMarkers[driverId] = marker;
                                }

                                var distance = haversine_distance(parentCoords, { lat: lat, lon: lon });
                                if (distance < {{ bus_near_distance_km }} && !alertedDrivers[driverId]) {
                                    alert(`🔔 Bus Alert: ${driverName}'s Bus is about to arrive!`);
                                    alertedDrivers[driverId] = true;
                                }
                            }
                        });
                    });
            });
        }
    }

    updateBusLocationsAndCheckAlerts();
    setInterval(updateBusLocationsAndCheckAlerts, 5000);
</script>
""")

ADD_CHILD_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<h2 class="text-center">Add a Child Profile</h2>
<form method="post" class="mt-4">
    <div class="mb-3">
        <label for="name" class="form-label">Child's Name</label>
        <input type="text" class="form-control" id="name" name="name" required>
    </div>
    <div class="mb-3">
        <label for="class" class="form-label">Class</label>
        <input type="text" class="form-control" id="class" name="class_name" required>
    </div>
    <div class="mb-3">
        <label for="driver" class="form-label">Assign to Driver</label>
        <select class="form-select" id="driver" name="driver_id" required>
            <option value="">Select a driver...</option>
            {% for driver in drivers %}
            <option value="{{ driver.id }}">{{ driver.name }}</option>
            {% endfor %}
        </select>
    </div>
    <button type="submit" class="btn btn-primary w-100 btn-custom">Add Child</button>
</form>
<div class="text-center mt-3">
    <a href="{{ url_for('parent_dashboard') }}">Back to Dashboard</a>
</div>
""")

COMPLAINTS_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<h2 class="text-center">Submit a Complaint</h2>
<form method="post" class="mt-4">
    <div class="mb-3">
        <label for="driver" class="form-label">Select Driver</label>
        <select class="form-select" id="driver" name="driver_id" required>
            <option value="">Choose...</option>
            {% for driver in drivers %}
            <option value="{{ driver.id }}">{{ driver.name }}</option>
            {% endfor %}
        </select>
    </div>
    <div class="mb-3">
        <label for="message" class="form-label">Complaint / Message</label>
        <textarea class="form-control" id="message" name="message" rows="5" placeholder="Enter your complaint here..." required></textarea>
    </div>
    <button type="submit" class="btn btn-warning w-100 btn-custom">Submit Complaint</button>
</form>
<div class="text-center mt-3">
    <a href="{{ url_for('parent_dashboard') }}">Back to Dashboard</a>
</div>
""")

ADMIN_DASHBOARD_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<h2 class="text-center">Admin Dashboard</h2>
<div class="mt-4">
    <h3 class="text-danger">Service Complaints</h3>
    <ul class="list-group">
        {% for complaint in complaints %}
        <li class="list-group-item">
            <p><strong>From:</strong> {{ complaint.parent_name }}</p>
            <p><strong>Regarding:</strong> {{ complaint.driver_name }}</p>
            <p class="text-muted"><small>Submitted: {{ complaint.timestamp }}</small></p>
            <p class="border p-2 rounded">{{ complaint.message }}</p>
        </li>
        {% else %}
        <li class="list-group-item text-muted">No complaints to display.</li>
        {% endfor %}
    </ul>
</div>
""")

ERROR_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<div class="text-center">
    <h2 class="text-danger">Error {{ code }}</h2>
    <p>{{ message }}</p>
    <a href="{{ url_for('home') }}" class="btn btn-primary btn-custom">Return to Home</a>
</div>
""")

# ----------------------------
# Database helpers
# ----------------------------
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    cur = db.cursor()
    # Drop tables to ensure fresh start for schema changes
    cur.execute("DROP TABLE IF EXISTS parents")
    cur.execute("DROP TABLE IF EXISTS drivers")
    cur.execute("DROP TABLE IF EXISTS children")
    cur.execute("DROP TABLE IF EXISTS feedback")
    cur.execute("DROP TABLE IF EXISTS complaints")
    cur.execute("DROP TABLE IF EXISTS users")

    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS parents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        username TEXT UNIQUE,
        password TEXT,
        phone TEXT,
        photo TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS drivers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        username TEXT UNIQUE,
        password TEXT,
        phone TEXT,
        photo TEXT,
        lat REAL,
        lon REAL,
        last_updated TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS children (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        class_name TEXT,
        parent_id INTEGER,
        driver_id INTEGER,
        FOREIGN KEY (parent_id) REFERENCES parents(id),
        FOREIGN KEY (driver_id) REFERENCES drivers(id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER,
        driver_id INTEGER,
        rating INTEGER,
        message TEXT,
        timestamp TEXT,
        FOREIGN KEY (parent_id) REFERENCES parents(id),
        FOREIGN KEY (driver_id) REFERENCES drivers(id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS complaints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER,
        driver_id INTEGER,
        message TEXT,
        timestamp TEXT,
        FOREIGN KEY (parent_id) REFERENCES parents(id),
        FOREIGN KEY (driver_id) REFERENCES drivers(id)
    )""")
    db.commit()

    # Add dummy data for a realistic demo
    if not cur.execute("SELECT id FROM users WHERE username = 'admin'").fetchone():
        db.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                   ('admin', generate_password_hash('pass'), 'admin'))
    if not cur.execute("SELECT id FROM parents WHERE username = 'parent1'").fetchone():
        db.execute("INSERT INTO parents (name, username, password, phone, photo) VALUES (?, ?, ?, ?, ?)",
                   ('Parent One', 'parent1', generate_password_hash('pass'), '919876543210', 'static/default_profile.png'))
    if not cur.execute("SELECT id FROM drivers WHERE username = 'driver1'").fetchone():
        db.execute("INSERT INTO drivers (name, username, password, phone, photo, lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   ('Driver One', 'driver1', generate_password_hash('pass'), '919988776655', 'static/default_profile.png', 28.7041, 77.1025))
    if not cur.execute("SELECT id FROM children").fetchone():
        db.execute("INSERT INTO children (name, class_name, parent_id, driver_id) VALUES (?, ?, ?, ?)",
                   ('Child A', 'Class 5', 1, 1))
        db.execute("INSERT INTO children (name, class_name, parent_id, driver_id) VALUES (?, ?, ?, ?)",
                   ('Child B', 'Class 3', 1, 1))
    db.commit()

# Initialize DB once at startup
with app.app_context():
    init_db()

# ----------------------------
# Authentication helpers
# ----------------------------
def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'user_id' not in session:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for('home'))
            if role and session.get('role') != role:
                flash("You do not have permission to view this page.", "danger")
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return wrapped
    return decorator

def get_user_data(role, user_id):
    db = get_db()
    cur = db.execute(f"SELECT * FROM {role} WHERE id = ?", (user_id,))
    return cur.fetchone()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371 # Radius of Earth in kilometers
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    distance = R * c
    return distance

# ----------------------------
# Routes
# ----------------------------
@app.route("/")
def home():
    return render_template_string(HOME_TEMPLATE)

@app.route("/<role>_register", methods=["GET", "POST"])
def register(role):
    if role not in ["parent", "driver"]:
        return render_template_string(ERROR_TEMPLATE, code=404, message="Invalid role")
    
    table = f"{role}s"
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        phone = request.form.get("phone", "").strip()
        photo = request.files.get("photo")

        if not all([name, username, password, phone]):
            flash("Please fill all required fields.", "danger")
        else:
            db = get_db()
            cur = db.execute(f"SELECT id FROM {table} WHERE username = ?", (username,))
            if cur.fetchone():
                flash("Username already exists.", "danger")
            else:
                hashed = generate_password_hash(password)
                photo_path = DEFAULT_PROFILE_IMG
                if photo and allowed_file(photo.filename):
                    fname = secure_filename(photo.filename)
                    photo_path = os.path.join("uploads", fname)
                    photo.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                
                db.execute(f"INSERT INTO {table} (name, username, password, phone, photo) VALUES (?, ?, ?, ?, ?)",
                            (name, username, hashed, phone, photo_path))
                db.commit()
                flash("Registration successful. You can log in.", "success")
                return redirect(url_for("login", role=role))
    
    return render_template_string(REGISTER_TEMPLATE, role=role)

@app.route("/<role>_login", methods=["GET", "POST"])
def login(role):
    if role not in ["parent", "driver"]:
        return render_template_string(ERROR_TEMPLATE, code=404, message="Invalid role")
        
    table = f"{role}s"
    
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        cur = db.execute(f"SELECT id, password FROM {table} WHERE username = ?", (username,))
        row = cur.fetchone()
        
        if row and check_password_hash(row["password"], password):
            session['user_id'] = row["id"]
            session['role'] = table
            flash(f"Welcome, {username}!", "success")
            return redirect(url_for(f"{role}_dashboard"))
        flash("Invalid username or password.", "danger")
    
    return render_template_string(LOGIN_TEMPLATE, role=role)

@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        db = get_db()
        user = db.execute("SELECT id, password FROM users WHERE username = ? AND role = 'admin'", (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['role'] = 'admin'
            flash("Logged in as Admin.", "success")
            return redirect(url_for('admin_dashboard'))
        flash("Invalid credentials.", "danger")
    return render_template_string(LOGIN_TEMPLATE, role='admin')

@app.route("/edit_profile", methods=["GET", "POST"])
@login_required()
def edit_profile():
    user_id = session.get('user_id')
    role = session.get('role')
    user = get_user_data(role, user_id)
    
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        photo = request.files.get("photo")

        if not all([name, phone]):
            flash("Please fill all required fields.", "danger")
        else:
            photo_path = user['photo']
            if photo and allowed_file(photo.filename):
                fname = secure_filename(photo.filename)
                photo_path = os.path.join("uploads", fname)
                photo.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            
            db = get_db()
            db.execute(f"UPDATE {role} SET name = ?, phone = ?, photo = ? WHERE id = ?",
                       (name, phone, photo_path, user_id))
            db.commit()
            flash("Profile updated successfully!", "success")
            return redirect(url_for("edit_profile"))

    photo_url = url_for("uploaded_file", filename=os.path.basename(user['photo'])) if "uploads/" in user['photo'] else url_for('static', filename=os.path.basename(user['photo']))
    return render_template_string(EDIT_PROFILE_TEMPLATE, user=user, photo_url=photo_url)

# ----------------------------
# Dashboards (protected)
# ----------------------------
@app.route("/parent_dashboard")
@login_required(role="parents")
def parent_dashboard():
    user = get_user_data("parents", session.get('user_id'))
    db = get_db()
    children_cur = db.execute("""
        SELECT c.name, c.class_name, d.name AS driver_name
        FROM children c JOIN drivers d ON c.driver_id = d.id
        WHERE c.parent_id = ?
    """, (user['id'],)).fetchall()
    
    photo_url = url_for("uploaded_file", filename=os.path.basename(user['photo'])) if "uploads/" in user['photo'] else url_for('static', filename=os.path.basename(user['photo']))
    return render_template_string(PARENT_DASHBOARD_TEMPLATE, user=user, children=children_cur, photo_url=photo_url)

@app.route("/add_child", methods=["GET", "POST"])
@login_required(role="parents")
def add_child():
    db = get_db()
    if request.method == "POST":
        name = request.form.get('name')
        class_name = request.form.get('class_name')
        driver_id = request.form.get('driver_id')
        if not all([name, class_name, driver_id]):
            flash("Please fill all fields.", "danger")
        else:
            db.execute("INSERT INTO children (name, class_name, parent_id, driver_id) VALUES (?, ?, ?, ?)",
                       (name, class_name, session['user_id'], driver_id))
            db.commit()
            flash("Child profile added successfully!", "success")
            return redirect(url_for('parent_dashboard'))
    
    drivers = db.execute("SELECT id, name FROM drivers").fetchall()
    return render_template_string(ADD_CHILD_TEMPLATE, drivers=drivers)

@app.route("/driver_dashboard")
@login_required(role="drivers")
def driver_dashboard():
    user = get_user_data("drivers", session.get('user_id'))
    
    # Calculate average rating
    db = get_db()
    cur = db.execute("SELECT AVG(rating) as avg_rating, COUNT(*) as total_ratings FROM feedback WHERE driver_id = ?", (user['id'],))
    result = cur.fetchone()
    rating = result['avg_rating']
    total_ratings = result['total_ratings']

    # Get child list with parent info for WhatsApp link
    children_cur = db.execute("""
        SELECT c.name AS child_name, p.name AS parent_name, p.phone AS parent_phone
        FROM children c JOIN parents p ON c.parent_id = p.id
        WHERE c.driver_id = ?
    """, (user['id'],)).fetchall()
    
    children = []
    for c in children_cur:
        message = f"Hi {c['parent_name']}, the bus has arrived at {c['child_name']}'s stop. Have a great day!"
        wa_link = f"https://wa.me/{c['parent_phone']}?text={urllib.parse.quote_plus(message)}"
        children.append({
            'child_name': c['child_name'],
            'wa_link': wa_link
        })

    photo_url = url_for("uploaded_file", filename=os.path.basename(user['photo'])) if "uploads/" in user['photo'] else url_for('static', filename=os.path.basename(user['photo']))
    return render_template_string(DRIVER_DASHBOARD_TEMPLATE, user=user, photo_url=photo_url, rating=rating, total_ratings=total_ratings, children=children)

@app.route("/admin_dashboard")
@login_required(role="admin")
def admin_dashboard():
    db = get_db()
    complaints_cur = db.execute("""
        SELECT c.message, c.timestamp, p.name AS parent_name, d.name AS driver_name
        FROM complaints c
        JOIN parents p ON c.parent_id = p.id
        JOIN drivers d ON c.driver_id = d.id
        ORDER BY c.timestamp DESC
    """).fetchall()
    return render_template_string(ADMIN_DASHBOARD_TEMPLATE, complaints=complaints_cur)

# ----------------------------
# Bus Map and API
# ----------------------------
@app.route("/bus_map")
@login_required(role="parents")
def bus_map():
    db = get_db()
    cur = db.execute("SELECT id, name, lat, lon FROM drivers WHERE lat IS NOT NULL AND lon IS NOT NULL")
    drivers = cur.fetchall()
    return render_template_string(BUS_MAP_TEMPLATE, drivers=drivers, school_lat=SCHOOL_LOCATION['lat'], school_lon=SCHOOL_LOCATION['lon'], bus_near_distance_km=BUS_NEAR_DISTANCE_KM)

@app.route("/bus_locations")
@login_required(role="parents")
def bus_locations():
    db = get_db()
    cur = db.execute("SELECT id, name, phone, photo, lat, lon, last_updated FROM drivers WHERE lat IS NOT NULL AND lon IS NOT NULL")
    drivers = cur.fetchall()
    
    locations = []
    for driver in drivers:
        photo_url = url_for("uploaded_file", filename=os.path.basename(driver['photo'])) if "uploads/" in driver['photo'] else url_for('static', filename=os.path.basename(driver['photo']))
        
        distance = calculate_distance(driver['lat'], driver['lon'], SCHOOL_LOCATION['lat'], SCHOOL_LOCATION['lon'])
        eta_minutes = int((distance / AVERAGE_BUS_SPEED_KMPH) * 60)
        
        eta_string = f"{eta_minutes} mins" if eta_minutes > 0 else "Arrived!"

        cur_rating = db.execute("SELECT AVG(rating) as avg_rating FROM feedback WHERE driver_id = ?", (driver['id'],)).fetchone()['avg_rating']

        locations.append({
            'id': driver['id'],
            'name': driver['name'],
            'phone': driver['phone'],
            'photo': request.host_url.rstrip('/') + photo_url,
            'lat': driver['lat'],
            'lon': driver['lon'],
            'rating': cur_rating,
            'eta': eta_string,
            'last_updated': driver['last_updated']
        })
    return jsonify(drivers=locations)

@app.route("/update_location", methods=["POST"])
@login_required(role="drivers")
def update_location():
    try:
        data = request.get_json()
        lat = data.get('lat')
        lon = data.get('lon')

        if lat is None or lon is None:
            return jsonify({'status': 'error', 'message': 'Missing latitude or longitude'}), 400

        user_id = session.get('user_id')
        db = get_db()
        db.execute("UPDATE drivers SET lat = ?, lon = ?, last_updated = datetime('now') WHERE id = ?", (lat, lon, user_id))
        db.commit()
        return jsonify({'status': 'success', 'message': 'Location updated'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ----------------------------
# Feedback and Complaints
# ----------------------------
@app.route("/feedback", methods=["GET", "POST"])
@login_required(role="parents")
def feedback():
    db = get_db()
    
    if request.method == "POST":
        driver_id = request.form.get("driver_id")
        rating = request.form.get("rating")
        message = request.form.get("message", "").strip()

        if not all([driver_id, rating]):
            flash("Please select a driver and a rating.", "danger")
        else:
            db.execute("INSERT INTO feedback (parent_id, driver_id, rating, message, timestamp) VALUES (?, ?, ?, ?, datetime('now'))",
                        (session['user_id'], driver_id, rating, message))
            db.commit()
            flash("Thank you for your feedback!", "success")
            return redirect(url_for('feedback'))

    drivers_cur = db.execute("SELECT id, name FROM drivers ORDER BY name").fetchall()
    
    past_feedback_cur = db.execute("""
        SELECT f.rating, f.message, d.name as driver_name
        FROM feedback f JOIN drivers d ON f.driver_id = d.id
        WHERE f.parent_id = ? ORDER BY f.timestamp DESC
    """, (session['user_id'],)).fetchall()

    return render_template_string(FEEDBACK_TEMPLATE, drivers=drivers_cur, past_feedback=past_feedback_cur)

@app.route("/submit_complaint", methods=["GET", "POST"])
@login_required(role="parents")
def submit_complaint():
    db = get_db()
    if request.method == "POST":
        driver_id = request.form.get("driver_id")
        message = request.form.get("message", "").strip()
        if not all([driver_id, message]):
            flash("Please select a driver and write your complaint.", "danger")
        else:
            db.execute("INSERT INTO complaints (parent_id, driver_id, message, timestamp) VALUES (?, ?, ?, datetime('now'))",
                       (session['user_id'], driver_id, message))
            db.commit()
            flash("Your complaint has been submitted. We will review it shortly.", "success")
            return redirect(url_for('parent_dashboard'))
    
    drivers_cur = db.execute("SELECT id, name FROM drivers ORDER BY name").fetchall()
    return render_template_string(COMPLAINTS_TEMPLATE, drivers=drivers_cur)


# ----------------------------
# Helpers: logout and file serves
# ----------------------------
@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route("/static/<filename>")
def static_file(filename):
    return send_from_directory(os.path.join(os.path.abspath(os.path.dirname(__file__)), "static"), filename)

# ----------------------------
# Error handling
# ----------------------------
@app.errorhandler(413)
def request_entity_too_large(error):
    return render_template_string(ERROR_TEMPLATE, code=413, message="File too large."), 413

@app.errorhandler(404)
def not_found(error):
    return render_template_string(ERROR_TEMPLATE, code=404, message="Page not found."), 404

@app.errorhandler(500)
def internal_error(error):
    logging.exception("Server error: %s", error)
    return render_template_string(ERROR_TEMPLATE, code=500, message="Server error. Please try again later."), 500

# ----------------------------
# Run
# ----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
