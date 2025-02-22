from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from astrobin.tests.generators import Generators
from astrobin_apps_equipment.tests.equipment_generators import EquipmentGenerators


class TestApiSoftwareViewSet(TestCase):
    def test_list_with_no_items(self):
        client = APIClient()

        response = client.get(reverse('astrobin_apps_equipment:software-list'), format='json')
        self.assertEquals(0, response.data['count'])

    def test_list_with_items(self):
        client = APIClient()

        software = EquipmentGenerators.software()

        response = client.get(reverse('astrobin_apps_equipment:software-list'), format='json')
        self.assertEquals(1, response.data['count'])
        self.assertEquals(software.name, response.data['results'][0]['name'])

    def test_deleting_not_allowed(self):
        client = APIClient()

        software = EquipmentGenerators.software()

        response = client.delete(reverse('astrobin_apps_equipment:software-detail', args=(software.pk,)), format='json')
        self.assertEquals(405, response.status_code)

        user = Generators.user(groups=['equipment_moderators'])
        client.login(username=user.username, password=user.password)
        client.force_authenticate(user=user)

        response = client.delete(reverse('astrobin_apps_equipment:software-detail', args=(software.pk,)), format='json')
        self.assertEquals(405, response.status_code)

    def test_post_not_allowed(self):
        client = APIClient()

        response = client.post(reverse('astrobin_apps_equipment:software-list'), {
            'brand': EquipmentGenerators.brand().pk,
            'name': 'Software Foo',
        }, format='json')
        self.assertEquals(403, response.status_code)

        user = Generators.user()
        client.login(username=user.username, password=user.password)
        client.force_authenticate(user=user)

        response = client.post(reverse('astrobin_apps_equipment:software-list'), {
            'brand': EquipmentGenerators.brand().pk,
            'name': 'Software Foo',
        }, format='json')
        self.assertEquals(403, response.status_code)

    def test_created_by(self):
        client = APIClient()

        user = Generators.user(groups=['equipment_moderators'])
        client.login(username=user.username, password=user.password)
        client.force_authenticate(user=user)

        response = client.post(reverse('astrobin_apps_equipment:software-list'), {
            'brand': EquipmentGenerators.brand().pk,
            'name': 'Software Foo',
        }, format='json')
        self.assertEquals(201, response.status_code)
        self.assertEquals(user.pk, response.data['created_by'])

    def test_list_returns_only_own_DIYs(self):
        user = Generators.user()
        first = EquipmentGenerators.software(created_by=user)
        first.brand = None
        first.save()

        second = EquipmentGenerators.software()
        second.brand = None
        second.save()

        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('astrobin_apps_equipment:software-list'), format='json')
        self.assertEquals(1, response.data['count'])
        self.assertEquals(first.name, response.data['results'][0]['name'])

    def test_find_recently_used_no_usages(self):
        user = Generators.user()

        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(
            reverse('astrobin_apps_equipment:software-list') + 'recently-used/', format='json'
        )

        self.assertEquals(0, len(response.data))

    def test_find_recently_used_one_usage(self):
        user = Generators.user()
        software = EquipmentGenerators.software(created_by=user)
        image = Generators.image(user=user)
        image.software_2.add(software)

        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(
            reverse('astrobin_apps_equipment:software-list') + 'recently-used/', format='json'
        )

        self.assertEquals(1, len(response.data))


