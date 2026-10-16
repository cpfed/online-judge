# Uzbek contest statements

Before importing Uzbek Polygon packages, append this **after any existing
LANGUAGES assignment** in the deployment's `dmoj/local_settings.py`:

```python
if not any(code == 'uz' for code, _name in LANGUAGES):
    LANGUAGES = [*LANGUAGES, ('uz', 'Uzbek')]
```

In the CPFED deployment, this configuration is maintained in
`cpfed/dmoj-docker/local_settings.py`; the image build copies it to
`/site/dmoj/local_settings.py`. It is not managed by this repository.

Keep `LANGUAGE_CODE` unchanged. Restart the Django application and Polygon Celery
workers so both use the same settings. The standard ProblemTranslation admin
then accepts Uzbek. No custom language setting, new model field, or database
schema migration is needed. Do not generate judge migrations for this deployment
configuration: upstream migration state contains historical language choices and
`makemigrations` can report choices-only differences.

The DMOJ footer deliberately omits Uzbek: participants select the content language
in cpfed-web while keeping the interface in Kazakh, Russian or English.

## Statement headings and Crowdin

The importer uses the existing Django gettext calls inside `override(language)`.
`locale/uz/LC_MESSAGES/django.po` supplies only its eight generated headings:
Input, Output, Interaction, Scoring, Samples, Input {}, Output {}, and Notes.
No Uzbek-specific Python dictionary or full Uzbek interface translation is needed.
The statement bodies themselves must still be translated in Polygon.

The catalog is included in the repository so it works before Crowdin is configured.
To maintain these translations through the existing Crowdin project:

1. A project administrator adds Uzbek (`uz`) as a target language in the project
   configured by `crowdin.yaml` (project ID `622648`).
2. Upload this catalog as Uzbek translations for the existing `django.po` source
   file, or enter the eight translations there. The English source already contains
   all eight strings. Keep the `{}` placeholders in the numbered sample headings.
3. Run the existing `updatemessages` workflow (also scheduled daily), review its
   translation PR, and merge it. Check that the eight translations are retained;
   an empty Crowdin catalog must not overwrite the bootstrapped translations.

Adding the catalog here does not enable Uzbek or upload translations in Crowdin.
Other interface strings may remain untranslated. Future statement languages can
use the same gettext mechanism once their language configuration and Polygon
mapping are supported.

Compile catalogs before running tests or starting import workers:

```sh
python manage.py compilemessages
```

This requires GNU gettext (`msgfmt`). Compiled `.mo` files are build artifacts, not
committed files. Both Django and Celery need the compiled catalogs. The current
`cpfed/dmoj-docker` build already runs this command in `dmoj/scripts/copy_static`
before packaging `dmoj-prod`, which is used by both services. Restart workers when
deploying updated translations. Headings are stored in imported descriptions, so
reimport a problem to apply later heading changes to an existing statement.

## Import and API behavior

Polygon accepts `uzbek` and `uz`; Russian, English and Kazakh mappings continue to
work. Supply the actual translations in the package. Import preserves every
statement as a ProblemTranslation, including a copy of the primary statement.
The primary remains the configured LANGUAGE_CODE when present, otherwise the
first statement in the package. Reimport replaces the translations with the
package contents, as before; manual translation edits should also be made in
Polygon to survive the next import.

The ESEP contest problem API accepts `?language=uz`. Missing translations return
the original and its language, inferred from a matching translation (configured
LANGUAGE_CODE first, then alphabetical language code). Historical problems without
a matching translation keep the previous LANGUAGE_CODE fallback. Reimport these
problems when their actual primary language needs to be known.

Deploy settings and backend first, then cpfed-web and its contest-field migration.
Import and check the statements before enabling Uzbek as a contest's default
content language. The public DMOJ v2 API is unchanged.

Regression tests: `python manage.py test judge.models.tests.test_statement_languages`.
They are also discovered by the existing CI command `python manage.py test judge`.
