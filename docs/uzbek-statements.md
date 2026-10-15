# Uzbek contest statements

Before importing Uzbek Polygon packages, append this **after any existing
LANGUAGES assignment** in the deployment's `dmoj/local_settings.py`:

```python
if not any(code == 'uz' for code, _name in LANGUAGES):
    LANGUAGES = [*LANGUAGES, ('uz', 'Uzbek')]
```

Keep `LANGUAGE_CODE` unchanged. Restart the Django application and Polygon Celery
workers so both use the same settings. The standard ProblemTranslation admin
then accepts Uzbek. No custom language setting, new model field, or database
schema migration is needed. Do not generate judge migrations for this deployment
configuration: upstream migration state contains historical language choices and
`makemigrations` can report choices-only differences.

The DMOJ footer deliberately omits Uzbek: participants select the content language
in cpfed-web while keeping the interface in Kazakh, Russian or English.

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
