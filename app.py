from flask import Flask, render_template, request
from solver import solve

app = Flask(__name__)


def checkbox_to_int(form, name: str) -> int:
    return 1 if form.get(name) == "on" else 0


def parse_consts(raw: str) -> dict:
    """
    支援格式：
    pi=3.1415926
    e=2.71828

    或者：
    pi=3.1415926, e=2.71828, phi=1.6180339
    """
    consts = {}
    raw = raw.strip()
    if not raw:
        return consts

    # 允許換行或逗號分隔
    parts = raw.replace("\n", ",").split(",")

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if "=" not in part:
            raise ValueError(f"常數格式錯誤：{part}，請用 name=value")

        name, value_text = part.split("=", 1)
        name = name.strip()
        value_text = value_text.strip()

        if not name:
            raise ValueError("常數名稱不能是空的")

        try:
            value = float(value_text)
        except ValueError:
            raise ValueError(f"常數 {name} 的值不是合法數字：{value_text}")

        consts[name] = value

    return consts


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    form_data = {
        "target": "",
        "N": "3",
        "generation_depth": "10",
        "max_seconds": "10",
        "memory_limit_mb": "512",
        "consts": "",
        "use_neg": False,
        "use_pow": False,
        "use_sin": False,
        "use_cos": False,
        "use_tan": False,
        "use_exp": False,
        "use_ln": False,
        "use_sqrt": False,
    }

    if request.method == "POST":
        try:
            form_data["target"] = request.form.get("target", "")
            form_data["N"] = request.form.get("N", "3")
            form_data["generation_depth"] = request.form.get("generation_depth", "10")
            form_data["max_seconds"] = request.form.get("max_seconds", "10")
            form_data["memory_limit_mb"] = request.form.get("memory_limit_mb", "512")
            form_data["consts"] = request.form.get("consts", "")

            for key in [
                "use_neg", "use_pow", "use_sin", "use_cos",
                "use_tan", "use_exp", "use_ln", "use_sqrt"
            ]:
                form_data[key] = (request.form.get(key) == "on")

            target = float(form_data["target"])
            consts = parse_consts(form_data["consts"])

            config = {
                "N": int(form_data["N"]),
                "generation_depth": int(form_data["generation_depth"]),
                "max_seconds": float(form_data["max_seconds"]),
                "verbose": 0,
                "keep_top": 1,
                "memory_limit_mb": int(form_data["memory_limit_mb"]),
                "consts": consts,
                "use_neg": 1 if form_data["use_neg"] else 0,
                "use_pow": 1 if form_data["use_pow"] else 0,
                "use_sin": 1 if form_data["use_sin"] else 0,
                "use_cos": 1 if form_data["use_cos"] else 0,
                "use_tan": 1 if form_data["use_tan"] else 0,
                "use_exp": 1 if form_data["use_exp"] else 0,
                "use_ln": 1 if form_data["use_ln"] else 0,
                "use_sqrt": 1 if form_data["use_sqrt"] else 0,
            }

            value, expr = solve(target, config)

            result = {
                "target": target,
                "value": value,
                "expr": expr,
                "abs_error": abs(value - target),
                "consts": consts,
            }

        except Exception as e:
            error = str(e)

    return render_template(
        "index.html",
        result=result,
        error=error,
        form_data=form_data,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
