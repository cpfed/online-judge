from django.conf import settings


def resolve_statement(problem, language):
    """Return text and its actual language without changing upstream Problem models."""
    if language:
        candidates = [language]
        if '-' in language:
            candidates.append(language.split('-')[0])
        for candidate in candidates:
            translation = problem.translations.filter(language=candidate).first()
            if translation is not None:
                return {
                    'name': translation.name,
                    'description': translation.description,
                    'language': translation.language,
                    'translated': True,
                }

    # Polygon preserves every source language, including the primary statement.
    originals = list(problem.translations.filter(
        name=problem.name, description=problem.description,
    ).values_list('language', flat=True))
    original_language = min(
        originals, key=lambda code: (code != settings.LANGUAGE_CODE, code),
    ) if originals else settings.LANGUAGE_CODE
    return {
        'name': problem.name,
        'description': problem.description,
        'language': original_language,
        'translated': False,
    }
