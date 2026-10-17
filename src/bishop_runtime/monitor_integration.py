"""Bind native progress to explicitly selected output destinations."""
from contextlib import contextmanager
import logging
import os

_LOG = logging.getLogger(__name__)


@contextmanager
def terminal_watch(runtime, config, output, actor='local', session_id=None):
    monitor = getattr(runtime, 'progress', None)
    settings = config.get('monitoring', {})
    if monitor is None or not settings.get('enabled', True) or not settings.get('terminal', True):
        yield
        return
    from .progress_transports import TerminalProgress
    sink = TerminalProgress(output)
    try:
        with monitor.subscribe(sink, actor=actor, session_id=session_id):
            yield
    finally:
        sink.close()


def configure_remote(runtime, home, config):
    """No sends during setup. Environment references never inherit other agents."""
    monitor = getattr(runtime, 'progress', None)
    settings = config['monitoring']
    if monitor is None or not settings['enabled']:
        return
    from .progress_transports import DiscordWebhook, WhatsAppBridge, ProgressCards
    for channel in ('discord', 'whatsapp'):
        if not settings[channel]:
            continue
        try:
            if channel == 'discord':
                destination = os.environ.get(settings['discord_webhook_env'], '')
                transport = DiscordWebhook(destination)
                target = destination
            else:
                destination = os.environ.get(settings['whatsapp_bridge_env'], '')
                chat = os.environ.get(settings['whatsapp_chat_env'], '')
                transport = WhatsAppBridge(destination, chat)
                target = destination + '\0' + chat
            cards = ProgressCards(home, transport.send, transport.edit, channel, target,
                                  rollover_seconds=840 if channel == 'whatsapp' else None)
            subscription = monitor.subscribe(cards)
            subscription.__enter__()
            monitor.add_cleanup(lambda subscription=subscription: subscription.__exit__(None, None, None))
            monitor.add_cleanup(cards.close)
        except Exception:
            # URL/key-bearing exception text must not enter logs.
            _LOG.warning('Bishop %s progress destination unavailable; task execution continues', channel)
