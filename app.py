from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/api/solve', methods=['POST'])
def solve_expression():
    data = request.json
    expression = data.get('expression', '')
    # Logic to solve the mathematical expression goes here
    # Placeholder for actual implementation
    result = eval(expression)  # Dangerous! Replace with a safe eval method
    return jsonify({'result': result})

@app.route('/api/config', methods=['GET', 'POST'])
def manage_config():
    if request.method == 'POST':
        config_data = request.json
        # Logic to save configuration data
        return jsonify({'message': 'Configuration saved'}), 201
    else:
        # Logic to return current configuration
        return jsonify({'config': 'current_configuration'})

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    app.run(debug=True)