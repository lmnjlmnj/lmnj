from flask import Flask, request, jsonify
import json

app = Flask(__name__)

solvers = {
    'default': {'precision': 2},
}

@app.route('/solve', methods=['POST'])
def solve_expression():
    data = request.get_json()
    expression = data.get('expression')
    solver_name = data.get('solver', 'default')
    if expression is None:
        return jsonify({'error': 'No expression provided'}), 400
    
    # Simple evaluation; in production, use a safer eval approach
    try:
        result = eval(expression)
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    
    precision = solvers[solver_name].get('precision', 2)
    return jsonify({'result': round(result, precision)})

@app.route('/config', methods=['GET', 'POST'])
def manage_config():
    if request.method == 'POST':
        data = request.get_json()
        solver_name = data.get('solver')
        precision = data.get('precision')
        if solver_name and isinstance(precision, int):
            solvers[solver_name] = {'precision': precision}
            return jsonify({'message': 'Solver configuration updated'}), 200
        return jsonify({'error': 'Invalid configuration'}), 400
    return jsonify(solvers)

if __name__ == '__main__':
    app.run(debug=True)