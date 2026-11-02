"""Read-only checks of the 23 saved HTTP responses; no browser execution."""
import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VOID = set('area base br col embed hr img input link meta param source track wbr'.split())


class Node:
    def __init__(self, tag='', attrs=None, text=''):
        self.tag, self.attrs, self.text = tag, dict(attrs or []), text
        self.children, self.parent = [], None

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def content(self):
        return self.text + ''.join(child.content() for child in self.children
                                   if child.tag not in {'script', 'style'})


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.root = Node('document')
        self.stack = [self.root]
        self.ids = {}
        self.feed(html)
        # React streams late children into P:* placeholders. Resolve these
        # static references without evaluating any response JavaScript.
        for source_id, target_id in re.findall(r'\$RS\("([^"]+)","([^"]+)"\)', html):
            source, target = self.ids[source_id], self.ids[target_id]
            parent = target.parent
            index = parent.children.index(target)
            parent.children[index:index + 1] = source.children
            for child in source.children:
                child.parent = parent
            source.parent.children.remove(source)
            source.children = []

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        node.parent = self.stack[-1]
        node.parent.children.append(node)
        if 'id' in node.attrs:
            self.ids[node.attrs['id']] = node
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        node = Node(text=data)
        node.parent = self.stack[-1]
        node.parent.children.append(node)


def normalize(text):
    return re.sub(r'\s+', '', text)


manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
checks = []
for game in manifest['games']:
    stem = ROOT / game['id']
    api = json.loads(stem.with_suffix('.json').read_text(encoding='utf-8'))
    doc = Document(stem.with_suffix('.html').read_text(encoding='utf-8'))
    phases = [node for node in doc.root.walk()
              if 'timeline-phase' in node.attrs.get('class', '').split()]
    expected = api['timeline']['phases']
    actual_order = [
        (int(phase.attrs['data-day']), phase.attrs['data-phase'],
         [node.attrs['data-slot'] for node in phase.walk() if 'data-slot' in node.attrs])
        for phase in phases
    ]
    expected_order = [(phase['number'], phase['phase'], [item['slot'] for item in phase['items']])
                      for phase in expected]
    text_failures = []
    for phase, reference in zip(phases, expected):
        nodes = [node for node in phase.walk() if 'data-slot' in node.attrs]
        for node, item in zip(nodes, reference['items']):
            if item.get('text') and normalize(item['text']) not in normalize(node.content()):
                text_failures.append({'phase': reference['label'], 'slot': item['slot']})
    ballots = [item['ballot']['id'] for phase in expected for item in phase['items']
               if item['kind'] == 'ballot']
    phase_order = [(phase['number'], 0 if phase['phase'] == 'night' else 1) for phase in expected]
    checks.append({
        'id': game['id'],
        'api_release_matches': api['release_id'] == manifest['release']['id'],
        'html_slots_match_api': actual_order == expected_order,
        'html_has_all_api_event_text': not text_failures,
        'missing_text': text_failures,
        'phase_order_increasing': phase_order == sorted(set(phase_order)),
        'emitted_ballots': len(ballots),
        'api_ballots': len(api['voting']['ballots']),
        'missing_ballot_ids': [ballot['id'] for ballot in api['voting']['ballots']
                               if ballot['id'] not in ballots],
    })

report = {
    'mode': 'partial',
    'checked_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
    'release_id': manifest['release']['id'],
    'games': len(checks),
    'method': 'Saved HTTP responses; React P:* child fragments statically reassembled.',
    'browser_visual_check': 'Not performed: browser access host unavailable; native 360 access not approved.',
    'checks': checks,
}
(ROOT / 'page_api_checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print({key: sum(check[key] for check in checks) for key in
       ['api_release_matches', 'html_slots_match_api', 'html_has_all_api_event_text', 'phase_order_increasing']})
print('API ballots:', sum(check['api_ballots'] for check in checks),
      'rendered:', sum(check['emitted_ballots'] for check in checks))
print('Mismatches:', [check for check in checks if not all(check[key] for key in
      ['api_release_matches', 'html_slots_match_api', 'html_has_all_api_event_text', 'phase_order_increasing'])])
