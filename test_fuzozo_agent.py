import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import fuzozo_agent as agent


class AgentBoundaryTests(unittest.TestCase):
    def test_overlong_model_reply_is_rephrased_not_truncated(self):
        backend = SimpleNamespace(reply=Mock(side_effect=[
            'This answer has far too many words for the small robot.', 'Hello from the lab.']))
        messages = [{'role': 'user', 'content': 'Hello'}]
        original = [dict(m) for m in messages]
        self.assertEqual(agent.short_reply(backend, None, {}, messages), 'Hello from the lab.')
        self.assertEqual(messages, original)
        self.assertEqual(backend.reply.call_count, 2)

    def test_noncompliant_second_reply_stops_before_robot_access(self):
        backend = SimpleNamespace(reply=Mock(return_value='word ' * 30))
        history = [{'role': 'system', 'content': 'system'}]
        with patch.object(agent, 'render') as render, patch.object(agent, 'Console') as console:
            with self.assertRaises(ValueError):
                agent.turn(backend, None, {}, history, 'Hello')
            render.assert_not_called()
            console.assert_not_called()
        self.assertEqual(history, [{'role': 'system', 'content': 'system'}])

    def test_multiple_usb_candidates_are_not_guessed(self):
        candidates = [SimpleNamespace(device=p, vid=0x1a86, pid=0x7523) for p in ('/dev/a', '/dev/b')]
        with patch.object(agent.list_ports, 'comports', return_value=candidates):
            with self.assertRaises(ValueError):
                agent.selected_port(None)

    def test_explicit_port_still_passes_to_identity_checked_console(self):
        self.assertEqual(agent.selected_port('/dev/chosen'), '/dev/chosen')


if __name__ == '__main__':
    unittest.main()
