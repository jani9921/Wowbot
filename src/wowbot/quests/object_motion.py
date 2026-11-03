"""Reviewed post-use movement hints; no input or target identity authority."""
import re


def pull_subject(description):
    # A lever/enemy pull does not instruct backpedalling. This reviewed
    # family is plant pulling, with the exact goober spell checked below.
    match = re.fullmatch(r'\s*(?:\d+\s*/\s*\d+\s*)?pull\s+(?:the\s+)?'
                         r'([\w\s\'-]*\bweeds?)\s*[.!]?\s*', str(description or ''), re.I)
    return match.group(1).strip() if match else None


def motion_for_template(description, template, spell_name):
    subject = pull_subject(description)
    if (not subject or subject.casefold() != str(template.get('name') or '').casefold()
            or template.get('type') != 10
            or str(spell_name or '').casefold() != 'pulling weeds'):
        return None
    return {'object_id': template['entry'], 'name': template['name'],
            'spell_id': template['Data10'], 'motion': 'PULL_BACKWARD',
            'source': 'OBJECTIVE_TEXT_AND_TDB_GOOBER_SPELL',
            'confirmed': False, 'navigation_trusted': False}
