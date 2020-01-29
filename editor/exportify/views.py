import io
import mapzen.whosonfirst.validator

from . import exportify_bp
from flask import (
    flash,
    json,
    make_response,
    render_template,
    redirect,
    request,
)


@exportify_bp.route("/exportify", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        file = request.files.get("input-file")
        text = request.form.get("input-text")

        # Accept either text in the form or text file upload (but not both)
        if file and text:
            flash("Please select a file or enter text in the box, not both.")
            return redirect(request.url)

        if not (file or text):
            flash("Upload a file or enter some JSON text to exportify.")
            return redirect(request.url)

        if file:
            if not (file.filename.endswith(".json") or file.filename.endswith(".geojson")):
                flash("Choose a .json or .geojson file")
                return redirect(request.url)

            content = file.read()

        elif text:
            content = text

        try:
            data = json.loads(content)
        except json.decoder.JSONDecodeError as e:
            flash("Content had invalid JSON: %s" % str(e))
            return redirect(request.url)

        if data.get("type") == "FeatureCollection":
            features = data.get("features")
        elif data.get("type") == "Feature":
            features = [data]
        else:
            flash("Content was not a GeoJSON Feature or FeatureCollection")
            return redirect(request.url)

        for feature in features:
            validator = mapzen.whosonfirst.validator.validator()
            report = validator.validate_feature(feature)

            if not report.ok():
                report_output = io.StringIO()
                report.print_report(report_output)
                report_output.seek(0)

                return report_output, 400

        exporter = mapzen.whosonfirst.export.string()
        result = exporter.export_feature(feature)

        response = make_response(result)
        response.content_type = 'application/json'
        return response

    return render_template("exportify/upload.html")
