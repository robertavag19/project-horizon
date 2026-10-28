"""Local flashcard scheduling adapter. No networking or model invocation."""
from datetime import timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from devtools.workers import WorkerError

FSRS_VERSION = '6.3.2'

def schedule(card, rating, now, engine='simple'):
    if rating not in ('Again','Hard','Good','Easy'):
        raise WorkerError('study_invalid_rating')
    if now.tzinfo is None or now.utcoffset() is None:
        raise WorkerError('study_review_requires_timezone')
    now=now.astimezone(timezone.utc)
    if engine=='simple':
        hours={'Again':1/6,'Hard':24,'Good':72,'Easy':168}[rating]
        return (now+timedelta(hours=hours)).isoformat(), None, 'simple-v1'
    if engine!='fsrs':raise WorkerError('study_unknown_scheduler')
    try:
        if version('fsrs')!=FSRS_VERSION:raise WorkerError('study_fsrs_version_unsupported')
        from fsrs import Card, Rating, Scheduler
    except (ImportError, PackageNotFoundError):
        raise WorkerError('study_fsrs_not_installed: use the project virtual environment and requirements-study.txt') from None
    try:
        state=card.get('scheduling')
        if state:
            if state.get('engine')!='fsrs' or state.get('version')!=FSRS_VERSION:
                raise WorkerError('study_fsrs_state_unsupported')
            current=Card.from_dict(state['card'])
            if current.last_review and now<current.last_review:
                raise WorkerError('study_review_time_before_last_review')
        else:
            current=Card(card_id=int(card['id'][:15],16),due=now)
        scheduler=Scheduler(desired_retention=.9,enable_fuzzing=False)
        updated,_=scheduler.review_card(current,Rating[rating],review_datetime=now)
        return updated.due.isoformat(), {'engine':'fsrs','version':FSRS_VERSION,
            'desired_retention':.9,'fuzzing':False,'card':updated.to_dict()}, 'fsrs-'+FSRS_VERSION
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        raise WorkerError('study_invalid_fsrs_state') from None
