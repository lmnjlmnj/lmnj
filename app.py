from flask import Flask, render_template, request
from solver import solve

app = Flask(__name__)

def checkbox_to_int(form, name: str) -> int:
    return 1 if form.get(name) == "on" else 0

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    if request.method == "POST":
        try:
            target = float(request.form["target"])

            config = {
                "N": int(request.form.get("N", 3)),
                "generation_depth": int(request.form.get("generation_depth", 10)),
                "max_seconds": float(request.form.get("max_seconds", 10)),
                "verbose": 0,
                "memory_limit_mb": int(request.form.get("memory_limit_mb", 512)),
                "use_neg": checkbox_to_int(request.form, "use_neg"),
                "use_pow": checkbox_to_int(request.form, "use_pow"),
                "use_sin": checkbox_to_int(request.form, "use_sin"),
                "use_cos": checkbox_to_int(request.form, "use_cos"),
                "use_tan": checkbox_to_int(request.form, "use_tan"),
                "use_exp": checkbox_to_int(request.form, "use_exp"),
                "use_ln": checkbox_to_int(request.form, "use_ln"),
                "use_sqrt": checkbox_to_int(request.form, "use_sqrt"),
            }

            value, expr = solve(target, config)

            result = {
                "target": target,
                "value": value,
                "expr": expr,
                "abs_error": abs(value - target),
            }

        except Exception as e:
            error = str(e)

    return render_template("index.html", result=result, error=error)

if __name__ == "__main__":
    app.run(debug=True)
