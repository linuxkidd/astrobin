# Python
from datetime import datetime, timedelta

from django.conf import settings
from mock import patch

from django.contrib.auth.models import User, Group
from django.urls import reverse_lazy
from django.test import TestCase, override_settings

from astrobin_apps_iotd.models import IotdSubmission, IotdVote

from astrobin.models import Image
from astrobin_apps_iotd.services import IotdService


class ExploreTest(TestCase):

    def setUp(self):
        self.submitter = User.objects.create_user('submitter_1', 'submitter_1@test.com', 'password')
        self.submitter2 = User.objects.create_user('submitter_2', 'submitter_2@test.com', 'password')
        self.submitters = Group.objects.create(name='iotd_submitters')
        self.submitters.user_set.add(self.submitter, self.submitter2)

        self.reviewer = User.objects.create_user('reviewer_1', 'reviewer_1@test.com', 'password')
        self.reviewer2 = User.objects.create_user('reviewer_2', 'reviewer_2@test.com', 'password')
        self.reviewers = Group.objects.create(name='iotd_reviewers')
        self.reviewers.user_set.add(self.reviewer, self.reviewer2)

        self.judges = Group.objects.create(name = 'iotd_judges')

        self.user = User.objects.create_user('user', 'user@test.com', 'password')
        self.client.login(username='user', password='password')
        self.client.post(
            reverse_lazy('image_upload_process'),
            {'image_file': open('astrobin/fixtures/test.jpg', 'rb')},
            follow=True)
        self.client.logout()
        self.image = Image.objects_including_wip.first()

        # Approve the image and set a title
        self.image.moderator_decision = 1
        self.image.title = "IOTD TEST IMAGE"
        self.image.data_source = "BACKYARD"
        self.image.save(keep_deleted=True)

    @override_settings(PREMIUM_RESTRICTS_IOTD=False)
    @override_settings(IOTD_SUBMISSION_MIN_PROMOTIONS=2)
    @override_settings(IOTD_REVIEW_MIN_PROMOTIONS=2)
    def test_top_picks_data_source_filter(self):
        IotdSubmission.objects.create(submitter=self.submitter, image=self.image)
        IotdSubmission.objects.create(submitter=self.submitter2, image=self.image)
        IotdVote.objects.create(reviewer=self.reviewer, image=self.image)
        IotdVote.objects.create(reviewer=self.reviewer2, image=self.image)

        self.image.published = datetime.now() - timedelta(settings.IOTD_REVIEW_WINDOW_DAYS) - timedelta(hours=1)
        self.image.save()

        IotdService().update_top_pick_archive()

        response = self.client.get(reverse_lazy('top_picks'))
        self.assertContains(response, self.image.title)

        response = self.client.get(reverse_lazy('top_picks') + '?source=backyard')
        self.assertContains(response, self.image.title)

        response = self.client.get(reverse_lazy('top_picks') + '?source=traveller')
        self.assertNotContains(response, self.image.title)

        self.image.data_source = 'TRAVELLER'
        self.image.save(keep_deleted=True)
        response = self.client.get(reverse_lazy('top_picks') + '?source=traveller')
        self.assertContains(response, self.image.title)
        response = self.client.get(reverse_lazy('top_picks') + '?source=backyard')
        self.assertNotContains(response, self.image.title)

        self.image.data_source = 'OWN_REMOTE'
        self.image.save(keep_deleted=True)
        response = self.client.get(reverse_lazy('top_picks') + '?source=own-remote')
        self.assertContains(response, self.image.title)
        response = self.client.get(reverse_lazy('top_picks') + '?source=traveller')
        self.assertNotContains(response, self.image.title)

        self.image.data_source = 'AMATEUR_HOSTING'
        self.image.save(keep_deleted=True)
        response = self.client.get(reverse_lazy('top_picks') + '?source=amateur-hosting')
        self.assertContains(response, self.image.title)
        response = self.client.get(reverse_lazy('top_picks') + '?source=own-remote')
        self.assertNotContains(response, self.image.title)

        self.image.data_source = 'PUBLIC_AMATEUR_DATA'
        self.image.save(keep_deleted=True)
        response = self.client.get(reverse_lazy('top_picks') + '?source=public-amateur-data')
        self.assertContains(response, self.image.title)
        response = self.client.get(reverse_lazy('top_picks') + '?source=amateur-hosting')
        self.assertNotContains(response, self.image.title)

        self.image.data_source = 'PRO_DATA'
        self.image.save(keep_deleted=True)
        response = self.client.get(reverse_lazy('top_picks') + '?source=pro-data')
        self.assertContains(response, self.image.title)
        response = self.client.get(reverse_lazy('top_picks') + '?source=public-amateur-data')
        self.assertNotContains(response, self.image.title)

    @override_settings(PREMIUM_RESTRICTS_IOTD=False)
    @override_settings(IOTD_SUBMISSION_MIN_PROMOTIONS=2)
    @override_settings(IOTD_REVIEW_MIN_PROMOTIONS=2)
    def test_top_picks_acquisition_type_filter(self):
        IotdSubmission.objects.create(submitter=self.submitter, image=self.image)
        IotdSubmission.objects.create(submitter=self.submitter2, image=self.image)
        IotdVote.objects.create(reviewer=self.reviewer, image=self.image)
        IotdVote.objects.create(reviewer=self.reviewer2, image=self.image)

        self.image.published = datetime.now() - timedelta(settings.IOTD_REVIEW_WINDOW_DAYS) - timedelta(hours=1)
        self.image.save()

        IotdService().update_top_pick_archive()

        response = self.client.get(reverse_lazy('top_picks'))
        self.assertContains(response, self.image.title)

        response = self.client.get(reverse_lazy('top_picks') + '?acquisition_type=regular')
        self.assertContains(response, self.image.title)

        response = self.client.get(reverse_lazy('top_picks') + '?acquisition_type=eaa')
        self.assertNotContains(response, self.image.title)

        self.image.acquisition_type = 'EAA'
        self.image.save(keep_deleted=True)
        response = self.client.get(reverse_lazy('top_picks') + '?acquisition_type=eaa')
        self.assertContains(response, self.image.title)
        response = self.client.get(reverse_lazy('top_picks') + '?acquisition_type=regular')
        self.assertNotContains(response, self.image.title)

        self.image.acquisition_type = 'LUCKY'
        self.image.save(keep_deleted=True)
        response = self.client.get(reverse_lazy('top_picks') + '?acquisition_type=lucky')
        self.assertContains(response, self.image.title)
        response = self.client.get(reverse_lazy('top_picks') + '?acquisition_type=regular')
        self.assertNotContains(response, self.image.title)

        self.image.acquisition_type = 'DRAWING'
        self.image.save(keep_deleted=True)
        response = self.client.get(reverse_lazy('top_picks') + '?acquisition_type=drawing')
        self.assertContains(response, self.image.title)
        response = self.client.get(reverse_lazy('top_picks') + '?acquisition_type=regular')
        self.assertNotContains(response, self.image.title)

        self.image.acquisition_type = 'OTHER'
        self.image.save(keep_deleted=True)
        response = self.client.get(reverse_lazy('top_picks') + '?acquisition_type=other')
        self.assertContains(response, self.image.title)
        response = self.client.get(reverse_lazy('top_picks') + '?acquisition_type=regular')
        self.assertNotContains(response, self.image.title)
