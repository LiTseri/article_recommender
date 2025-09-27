from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Welcome to the AI Article Recommender!"

@app.route("/emails", methods=["GET"])
def get_emails():
    return "Emails fetched successfully!"

if __name__ == "__main__":
    app.run()

