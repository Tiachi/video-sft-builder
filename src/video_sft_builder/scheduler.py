"""Single-coordinator task heaps and shared marginal deficits; no model calls."""
from collections import Counter
from fractions import Fraction
import heapq

from .errors import ProtocolError
from .util import asset, digest, read_json

LANGUAGE = {'zh': 3, 'en': 7}
FORM = {'oe': 7, 'mcq': 3}
OPTIONS = {3: 1, 4: 7, 6: 2}
BRANCH_PIPELINE = {'general': 'academic2m_inspired', 'long': 'lv116k_inspired'}


def deficit_choice(counts, weights, allowed=None):
    allowed = set(weights if allowed is None else allowed)
    total = sum(counts.values())
    denominator = sum(weights.values())
    return max((key for key in weights if key in allowed),
               key=lambda key: (Fraction(weights[key], denominator) * (total + 1) - counts[key], str(key)))


class Scheduler:
    def __init__(self, config, store):
        self.config, self.store = config, store
        all_tasks = read_json(asset('configs/task_registry.json'))['tasks']
        self.tasks = {t['name']: t for t in all_tasks if t['status'] == 'proposed_enabled'}
        self.templates = read_json(asset('configs/question_templates.json'))['templates']
        self.task_counts, self.languages, self.forms, self.options, self.template_counts = (Counter() for _ in range(5))
        self.last_selected, self.sequence = Counter(), 0
        for entry in store.records('dispatch'):
            plan = entry['payload']
            if plan['phase'] == 'balance':
                sequence = plan.get('selection_sequence', 0)
                self.sequence = max(self.sequence, sequence)
                task = plan['assigned_slots'][0]['task']
                self.last_selected[task] = max(self.last_selected[task], sequence)
        for record in store.records('candidate'):
            candidate = record['payload']
            status = store.get('quality:' + candidate['id'])
            if not status or status['decision'] == 'pass':
                self.observe(candidate, 1)

    def observe(self, candidate, amount):
        self.task_counts[(candidate['branch'], candidate['task'])] += amount
        self.languages[candidate['language']] += amount
        self.forms[candidate['question_type']] += amount
        if candidate['question_type'] == 'mcq':
            self.options[candidate['num_options']] += amount
        self.template_counts[candidate['template_id']] += amount

    def _slot(self, name, task=None, blocked_combinations=None):
        blocked_combinations = blocked_combinations or set()
        allowed_forms = self.tasks[task]['question_types'] if task else list(FORM)
        possibilities = [(lang, form, option) for lang in LANGUAGE for form in allowed_forms
                         for option in (OPTIONS if form == 'mcq' else [0])
                         if (task, lang, form, option) not in blocked_combinations]
        if not possibilities:
            return None
        languages = {p[0] for p in possibilities}
        language = deficit_choice(self.languages, LANGUAGE, languages)
        forms = {p[1] for p in possibilities if p[0] == language}
        form = deficit_choice(self.forms, FORM, forms)
        option_counts = {p[2] for p in possibilities if p[:2] == (language, form)}
        options = deficit_choice(self.options, OPTIONS, option_counts) if form == 'mcq' else 0
        return {'slot_id': name, 'task': task, 'language': language, 'question_type': form, 'num_options': options}

    def _template_candidates(self, slot, tasks):
        values = [t for t in self.templates if t['task'] in tasks and t['language'] == slot['language']
                  and slot['question_type'] in t['supported_question_types']
                  and slot['question_type'] in self.tasks[t['task']]['question_types']]
        values.sort(key=lambda t: (self.template_counts[t['template_id']],
                                  digest([self.config.data['run']['seed'], slot['slot_id'], t['template_id']])))
        # Fit needs some templates for every compatible task, not just the first task.
        count = self.config.data['generation']['templates_per_slot']
        return [t for task in sorted(tasks) for t in [v for v in values if v['task'] == task][:count]]

    def plan(self, video, branch, phase, index, blocked_tasks, blocked_combinations):
        key = f'dispatch:{video["id"]}:{branch}:{phase}:{index:03d}'
        existing = self.store.get(key)
        if existing:
            return existing
        tasks = {name: task for name, task in self.tasks.items() if task['branch'] == branch and name not in blocked_tasks}
        if not tasks:
            return None
        if phase == 'fit':
            count = 2 if branch == 'general' else 1
            slots = []
            # Temporary language/form reservations ensure the two fit slots do not
            # both chase the same deficit. A single coordinator owns this block.
            for i in range(count):
                slot = self._slot(f'{branch}_fit_{i}')
                slots.append(slot)
                self.languages[slot['language']] += 1
                self.forms[slot['question_type']] += 1
                if slot['question_type'] == 'mcq':
                    self.options[slot['num_options']] += 1
            for slot in slots:
                self.languages[slot['language']] -= 1
                self.forms[slot['question_type']] -= 1
                if slot['question_type'] == 'mcq':
                    self.options[slot['num_options']] -= 1
        else:
            self.sequence += 1
            heap = [(self.task_counts[(branch, name)], self.last_selected[name],
                     digest([self.config.data['run']['seed'], name]), name) for name in tasks]
            heapq.heapify(heap)
            slot = None
            while heap and slot is None:
                *_, name = heapq.heappop(heap)
                slot = self._slot(f'{branch}_balance_{index}', name, blocked_combinations)
            if not slot:
                return None
            self.last_selected[slot['task']] = self.sequence
            slots = [slot]
        selected_templates = []
        allowed = set()
        for slot in slots:
            compatible = {name for name, task in tasks.items() if slot['question_type'] in task['question_types']}
            if slot['task']:
                compatible &= {slot['task']}
            values = self._template_candidates(slot, compatible)
            if not values:
                raise ProtocolError('No compatible templates; refusing paid dispatch')
            slot['allowed_tasks'] = sorted(compatible)
            selected_templates.extend(values)
            allowed.update(compatible)
        plan = {'request_id': digest(key)[:32], 'video_id': video['id'], 'branch': branch, 'phase': phase,
                'selection_sequence': self.sequence,
                'assigned_slots': slots, 'allowed_tasks': [self.tasks[name] for name in sorted(allowed)],
                'template_candidates': list({t['template_id']: t for t in selected_templates}.values())}
        return self.store.put(key, 'dispatch', video['id'], plan)
