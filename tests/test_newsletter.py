import os
from uuid import uuid4
from unittest.mock import patch

from test_admin import AdminTests
from app import storage


class NewsletterTests(AdminTests):
    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {'GMAIL_SMTP_USER': 'sender@example.com', 'GMAIL_APP_PASSWORD': 'fake', 'PUBLIC_SITE_URL': 'https://example.com'})
        env.start()
        self.addCleanup(env.stop)

    def signup(self, email='reader@example.com'):
        return self.client.post('/api/newsletter/subscribe', json={'email': email})

    def campaign(self, headers):
        response = self.client.post('/admin/api/newsletter', headers=headers, json={'id': str(uuid4()), 'subject': 'Foundation news', 'body': 'Hello community!\nA new update.'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    def test_signup_dedup_validation_and_unsubscribe(self):
        self.assertEqual(self.signup(' Reader@Example.com ').status_code, 200)
        self.assertEqual(self.signup().status_code, 200)
        self.assertEqual(len(storage.list_subscribers()), 1)
        self.assertEqual(self.signup('invalid').status_code, 422)
        token = storage.list_subscribers()[0]['token']
        url = '/newsletter/unsubscribe/' + token
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(len(storage.list_subscribers()), 1)  # Link scanners do not unsubscribe.
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(storage.list_subscribers(), [])
        self.signup()
        self.assertEqual(len(storage.list_subscribers()), 1)

    def test_private_individual_delivery_and_resume(self):
        self.signup()
        self.signup('second@example.com')
        self.assertEqual(self.client.get('/admin/api/newsletter').status_code, 401)
        headers = self.login()
        identifier = self.campaign(headers)
        path = f'/admin/api/newsletter/{identifier}/send'
        self.assertEqual(self.client.post(path).status_code, 403)
        with patch('app.newsletter.smtplib.SMTP') as smtp:
            smtp.return_value.__enter__.return_value.send_message.return_value = {}
            first = self.client.post(path, headers=headers).json()
            self.assertEqual((first['sent'], first['pending']), (1, 1))
            second = self.client.post(path, headers=headers).json()
            self.assertEqual((second['sent'], second['pending']), (2, 0))
            self.client.post(path, headers=headers)
            calls = smtp.return_value.__enter__.return_value.send_message.call_args_list
            self.assertEqual(len(calls), 2)
            for call in calls:
                message = call.args[0]
                self.assertEqual(len(message.get_all('To')), 1)
                self.assertNotIn(',', message['To'])
                self.assertIn('https://example.com/newsletter/unsubscribe/', message.get_content())

    def test_failure_unsubscribe_and_uncertain_send_not_retried(self):
        self.signup()
        headers = self.login()
        identifier = self.campaign(headers)
        path = f'/admin/api/newsletter/{identifier}/send'
        with patch('app.newsletter.smtplib.SMTP', side_effect=OSError('offline')) as smtp:
            self.assertEqual(self.client.post(path, headers=headers).json()['failed'], 1)
            self.client.post(path, headers=headers)
            self.assertEqual(smtp.call_count, 1)
        identifier = self.campaign(headers)
        token = storage.list_subscribers()[0]['token']
        storage.unsubscribe(token)
        with patch('app.newsletter.smtplib.SMTP') as smtp:
            result = self.client.post(f'/admin/api/newsletter/{identifier}/send', headers=headers)
            self.assertEqual(result.json()['skipped'], 1)
            smtp.assert_not_called()
        self.signup()
        identifier = self.campaign(headers)
        job = storage.get_newsletter(identifier)
        job['recipients'][0]['status'] = 'sending'
        storage.save_newsletter(job)
        with patch('app.newsletter.smtplib.SMTP') as smtp:
            self.assertEqual(self.client.post(f'/admin/api/newsletter/{identifier}/send', headers=headers).json()['sending'], 1)
            smtp.assert_not_called()

    def test_idempotent_create_conflicts_and_configuration(self):
        self.signup()
        headers = self.login()
        identifier = self.campaign(headers)
        self.client.post('/admin/api/newsletter', headers=headers, json={'id': identifier, 'subject': 'Duplicate request', 'body': 'Hello'})
        self.assertEqual(len(storage.list_newsletters()), 1)
        stale = storage.get_newsletter(identifier)
        storage.save_newsletter(storage.get_newsletter(identifier))
        with self.assertRaises(storage.ConflictError):
            storage.save_newsletter(stale)
        with patch.dict(os.environ, {'PUBLIC_SITE_URL': ''}):
            response = self.client.post(f'/admin/api/newsletter/{identifier}/send', headers=headers)
            self.assertEqual(response.status_code, 503)
        self.assertEqual(storage.get_newsletter(identifier)['recipients'][0]['status'], 'pending')

    def test_native_signup_fallback_and_versioned_script(self):
        response = self.client.post('/newsletter/subscribe', data={'email': 'Native@Example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('You’re on the list!', response.text)
        self.assertEqual(storage.list_subscribers()[0]['email'], 'native@example.com')
        invalid = self.client.post('/newsletter/subscribe', data={'email': 'invalid'})
        self.assertEqual(invalid.status_code, 422)
        with patch('app.newsletter.storage.subscribe', side_effect=storage.StorageError('offline')):
            failed = self.client.post('/newsletter/subscribe', data={'email': 'other@example.com'})
            self.assertEqual(failed.status_code, 503)
            self.assertIn('We couldn’t save your signup', failed.text)
        homepage = self.client.get('/').text
        self.assertIn('method="post" action="/newsletter/subscribe"', homepage)
        self.assertRegex(homepage, r'/js/main\.js\?v=[a-f0-9]{12}')
