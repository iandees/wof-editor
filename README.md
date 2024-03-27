# Write Field

A live version of the tool is available at [writefield.nextzen.org](https://writefield.nextzen.org/).

This repository has three core parts:

* `place/`: Business logic for the [Flask](https://flask.palletsprojects.com/en/3.0.x/)-based web editor for Who's On First place gazetteer record properties with a [Leaflet](https://leafletjs.com/)-based map viewer for assorted geometries. User account authentication is via [Github](https://github.com/) to propose a Pull Request with the changes.
* `templates/`: [Presentation](https://www.digitalocean.com/community/tutorials/how-to-use-templates-in-a-flask-application) logic using HTML templates for each web view, for the Flask app.
* `exportify/`: Bundled Python-based tools to validate changes and export as custom formatted Who's On First GeoJSON records that enable quick multi-line property diffs and single-line geometry diffs.

## Development

1. Clone this repository.

```shell
git clone git@github.com:iandees/wof-editor.git
```
2. Install dependencies:

From inside your checkout of the repo:

```shell
cd wof-editor
```

Install [pyenv](https://github.com/pyenv/pyenv) to make sure Pipenv has access to the right version of Python:

```shell
brew install pyenv
```

Then also install [pipenv](https://pipenv.pypa.io/en/latest/) for dependency management:

```shell
brew install pipenv
```

3. Configure your Python environment:

```shell
pipenv install --dev
```

_CAUTION: This step may complain about not having the required version of Python (3.11) and ask if you want to install it. Say yes. That'll take a while.  You might get hung up on geos/shapely here, depending on which version of gdal you have installed._

Then setup pipenv to get into the Python virtual environment you just created with those dependencies:

```shell
pipenv shell
```

4. Run the Flash app locally:

```shell
FLASK_DEBUG=true FLASK_APP=service_wsgi.py flask run
```

The web app can be loaded in a web browser at: 

- [http://127.0.0.1:5000/](http://127.0.0.1:5000/)

5. Production deploy

Uses [serverless](https://www.serverless.com/framework/docs-providers-aws-guide-deploying) system and assumes access to organization secrets, which are limited access for Github org admins only.

Create a file `config.prod.yaml` (reference `config.sample.yaml`), with contents like:

```shell
GITHUB_APP_ID: "sample_app_id"
GITHUB_APP_SECRET: "sample_app_secret"
SECRET_KEY: "sample_secret_key"
STRIP_STAGE_PATH: "true"
```

_NOTE: Swap out "sample" values above with "secret" values._

Then run the app:

```shell
serverless deploy --stage="prod"
```

View logs:

```shell
serverless logs --stage="prod" --function="app" --tail
```

## License

* All code is BSD-3