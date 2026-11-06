import os
import unittest
from dataclasses import asdict
from unittest.mock import patch

from src.ui.schemas import ChatResponse, SIGUNGU, UserProfile
from src.ui.service import answer
from streamlit.testing.v1 import AppTest


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'USE_MOCK': 'true'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.profile = UserProfile('창원시', 65, ['혼자 사심'])

    def test_topics_and_serialization(self):
        for question in ('기초연금', '돌봄', '복지시설', '치매'):
            response = answer(question, self.profile)
            self.assertIsInstance(response, ChatResponse)
            self.assertTrue(response.sources)
            self.assertIn('창원시', response.answer)
            self.assertIn('시연용', response.answer)
            self.assertFalse(response.need_call_129)
            self.assertIn('url', asdict(response)['sources'][0])

    def test_unknown_and_empty(self):
        self.assertTrue(answer('날씨', self.profile).need_call_129)
        with self.assertRaises(ValueError):
            answer('  ', self.profile)

    def test_profiles(self):
        self.assertEqual(len(set(SIGUNGU)), 18)
        for city in SIGUNGU:
            UserProfile(city, 65)
        for args in [('서울시', 65, []), ('창원시', -1, []), ('창원시', 121, []),
                     ('창원시', True, []), ('창원시', 65, ['알 수 없음']),
                     ('창원시', 65, ['해당 없음', '치매'])]:
            with self.assertRaises(ValueError):
                UserProfile(*args)

    def test_real_routing_and_invalid_mode(self):
        with patch.dict(os.environ, {'USE_MOCK': 'false'}):
            with self.assertRaises(NotImplementedError):
                answer('연금', self.profile)
            response = ChatResponse('실제 구현 응답')
            with patch('src.ui.rag_backend.answer', return_value=response) as backend:
                self.assertIs(answer(' 연금 ', self.profile), response)
                backend.assert_called_once_with('연금', self.profile)
        with patch.dict(os.environ, {'USE_MOCK': 'typo'}):
            with self.assertRaises(ValueError):
                answer('연금', self.profile)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'USE_MOCK': 'true'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = AppTest.from_file('src/ui/app.py').run()

    def test_chat_quick_question_and_persistence(self):
        app = self.app
        self.assertFalse(app.exception)
        app.selectbox[0].select('진주시').run()
        app.button[2].click().run()
        self.assertEqual(len(app.chat_message), 2)
        self.assertIn('진주시', app.session_state.messages[0][1].answer)
        app.chat_input[0].set_value('알 수 없는 질문').run()
        self.assertEqual(len(app.chat_message), 4)
        self.assertEqual(len(app.warning), 1)
        app.number_input[0].set_value(70).run()
        self.assertEqual(len(app.chat_message), 4)
        self.assertFalse(app.exception)

    def test_font_bounds(self):
        app = self.app
        for _ in range(6):
            app.button[0].click().run()
        self.assertEqual(app.session_state.font_size, 28)
        for _ in range(6):
            app.button[1].click().run()
        self.assertEqual(app.session_state.font_size, 20)

    def test_conflicting_conditions_and_backend_failure(self):
        app = self.app
        app.multiselect[0].set_value(['해당 없음', '치매']).run()
        app.button[2].click().run()
        self.assertTrue(app.error)
        self.assertEqual(len(app.chat_message), 0)
        app.multiselect[0].set_value([]).run()
        with patch.dict(os.environ, {'USE_MOCK': 'false'}):
            app.chat_input[0].set_value('연금').run()
        self.assertTrue(app.error)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state.messages), 0)


if __name__ == '__main__':
    unittest.main()
