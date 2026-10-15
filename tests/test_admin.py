import io
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app import storage
from app.admin import LOGIN_FAILURES


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {
            'LOCAL_DATA_DIR': self.temp.name, 'SUPABASE_URL': '', 'SUPABASE_SECRET_KEY': '',
            'SUPABASE_SERVICE_ROLE_KEY': '', 'VERCEL': '', 'ADMIN_PASSWORD': 'a-test-password-at-least-16',
            'ADMIN_SESSION_SECRET': 'test-session-secret-with-at-least-32-characters',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        LOGIN_FAILURES.clear()
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def login(self):
        response = self.client.get('/admin/login')
        self.assertEqual(response.status_code, 200)
        token = self.client.cookies.get('ppf_login')
        response = self.client.post('/admin/login', json={'password': os.environ['ADMIN_PASSWORD'], 'csrf': token})
        self.assertEqual(response.status_code, 204)
        from app.admin import signer
        session = signer().loads(self.client.cookies.get('ppf_admin'))
        return {'X-CSRF-Token': session['csrf']}

    def test_authentication_and_private_headers(self):
        self.assertEqual(self.client.get('/admin', follow_redirects=False).status_code, 303)
        for path in ['/admin/api/content', '/admin/api/messages']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertIn('no-store', response.headers['cache-control'])
        self.client.get('/admin/login')
        self.assertEqual(self.client.post('/admin/login', json={'password': os.environ['ADMIN_PASSWORD'], 'csrf': 'forged'}).status_code, 403)
        headers = self.login()
        content = self.client.get('/admin/api/content').json()
        self.assertEqual(self.client.put('/admin/api/content', json=content).status_code, 403)
        self.assertEqual(self.client.post('/admin/logout', headers=headers).status_code, 204)
        self.assertEqual(self.client.get('/admin/api/messages').status_code, 401)

    def test_save_render_conflict_and_escaping(self):
        headers = self.login()
        content = self.client.get('/admin/api/content').json()
        content['about_title'] = 'Updated heading'
        content['about_body'] = '<script>alert(1)</script>\n\nSecond paragraph'
        content['team'] = list(reversed(content['team']))
        content['team'][0]['name'] = 'New first person'
        response = self.client.put('/admin/api/content', json=content, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['revision'], 1)
        html = self.client.get('/').text
        self.assertIn('Updated heading', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('New first person', html)
        self.assertEqual(self.client.put('/admin/api/content', json=content, headers=headers).status_code, 409)
        # Persistence across independent storage calls, not an in-memory edit.
        self.assertEqual(storage.get_site()['about_title'], 'Updated heading')

    def test_upload_validation_and_public_image(self):
        headers = self.login()
        self.assertEqual(self.client.post('/admin/api/images', headers=headers, files={'file': ('bad.svg', b'<svg/>', 'image/svg+xml')}).status_code, 422)
        image = io.BytesIO()
        Image.new('RGB', (2000, 1000), 'red').save(image, 'PNG')
        response = self.client.post('/admin/api/images', headers=headers, files={'file': ('photo.png', image.getvalue(), 'image/png')})
        self.assertEqual(response.status_code, 200, response.text)
        media = self.client.get(response.json()['url'])
        self.assertEqual(media.headers['content-type'], 'image/jpeg')
        with Image.open(io.BytesIO(media.content)) as picture:
            self.assertEqual(picture.size, (1800, 900))
        content = self.client.get('/admin/api/content').json()
        content['hero_image'] = response.json()['url']
        self.assertEqual(self.client.put('/admin/api/content', headers=headers, json=content).status_code, 200)
        self.assertIn(response.json()['url'], self.client.get('/').text)
        self.assertEqual(self.client.get('/media/not-a-uuid').status_code, 422)

    def test_contact_inbox_read_status_and_email_failure(self):
        with patch('app.contact.smtplib.SMTP', side_effect=OSError('offline')):
            response = self.client.post('/api/contact', json={'name': 'Visitor', 'email': 'visitor@example.com', 'message': 'Hello foundation'})
        self.assertEqual(response.status_code, 200)
        headers = self.login()
        rows = self.client.get('/admin/api/messages').json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['message'], 'Hello foundation')
        self.assertEqual(rows[0]['delivery'], 'failed')
        self.assertFalse(rows[0]['is_read'])
        response = self.client.patch('/admin/api/messages/' + rows[0]['id'], headers=headers, json={'is_read': True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.get('/admin/api/messages').json()[0]['is_read'])
        self.assertEqual(self.client.get('/admin/api/messages?offset=50').json(), [])

    def test_no_silent_local_fallback_on_vercel(self):
        with patch.dict(os.environ, {'VERCEL': '1'}):
            with self.assertRaises(storage.StorageError):
                storage.get_site()

    def test_external_image_urls_rejected(self):
        headers = self.login()
        content = self.client.get('/admin/api/content').json()
        content['hero_image'] = 'https://other.example/photo.jpg'
        self.assertEqual(self.client.put('/admin/api/content', headers=headers, json=content).status_code, 422)
