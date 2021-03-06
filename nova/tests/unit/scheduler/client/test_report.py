#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock

import nova.conf
from nova import context
from nova import objects
from nova.objects import base as obj_base
from nova.scheduler.client import report
from nova import test
from nova.tests import uuidsentinel as uuids

CONF = nova.conf.CONF


class SchedulerReportClientTestCase(test.NoDBTestCase):

    def setUp(self):
        super(SchedulerReportClientTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.ks_sess_mock = mock.Mock()

        with test.nested(
                mock.patch('keystoneauth1.session.Session',
                           return_value=self.ks_sess_mock),
                mock.patch('keystoneauth1.loading.load_auth_from_conf_options')
        ) as (_auth_mock, _sess_mock):
            self.client = report.SchedulerReportClient()

    @mock.patch('keystoneauth1.session.Session')
    @mock.patch('keystoneauth1.loading.load_auth_from_conf_options')
    def test_constructor(self, load_auth_mock, ks_sess_mock):
        report.SchedulerReportClient()

        load_auth_mock.assert_called_once_with(CONF, 'placement')
        ks_sess_mock.assert_called_once_with(auth=load_auth_mock.return_value)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_ensure_resource_provider_exists_in_cache(self, get_rp_mock,
            create_rp_mock):
        # Override the client object's cache to contain a resource provider
        # object for the compute host and check that
        # _ensure_resource_provider() doesn't call _get_resource_provider() or
        # _create_resource_provider()
        self.client._resource_providers = {
            uuids.compute_node: mock.sentinel.rp
        }

        self.client._ensure_resource_provider(uuids.compute_node)
        self.assertFalse(get_rp_mock.called)
        self.assertFalse(create_rp_mock.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_ensure_resource_provider_get(self, get_rp_mock, create_rp_mock):
        # No resource provider exists in the client's cache, so validate that
        # if we get the resource provider from the placement API that we don't
        # try to create the resource provider.
        get_rp_mock.return_value = mock.sentinel.rp

        self.client._ensure_resource_provider(uuids.compute_node)

        get_rp_mock.assert_called_once_with(uuids.compute_node)
        self.assertEqual({uuids.compute_node: mock.sentinel.rp},
                          self.client._resource_providers)
        self.assertFalse(create_rp_mock.called)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_ensure_resource_provider_create_none(self, get_rp_mock,
            create_rp_mock):
        # No resource provider exists in the client's cache, and
        # _create_provider returns None, indicating there was an error with the
        # create call. Ensure we don't populate the resource provider cache
        # with a None value.
        get_rp_mock.return_value = None
        create_rp_mock.return_value = None

        self.client._ensure_resource_provider(uuids.compute_node)

        get_rp_mock.assert_called_once_with(uuids.compute_node)
        create_rp_mock.assert_called_once_with(uuids.compute_node,
                                               uuids.compute_node)
        self.assertEqual({}, self.client._resource_providers)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_create_resource_provider')
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_ensure_resource_provider_create(self, get_rp_mock,
            create_rp_mock):
        # No resource provider exists in the client's cache and no resource
        # provider was returned from the placement API, so verify that in this
        # case we try to create the resource provider via the placement API.
        get_rp_mock.return_value = None
        create_rp_mock.return_value = mock.sentinel.rp

        self.client._ensure_resource_provider(uuids.compute_node)

        get_rp_mock.assert_called_once_with(uuids.compute_node)
        create_rp_mock.assert_called_once_with(
                uuids.compute_node,
                uuids.compute_node,  # name param defaults to UUID if None
        )
        self.assertEqual({uuids.compute_node: mock.sentinel.rp},
                          self.client._resource_providers)

        create_rp_mock.reset_mock()
        self.client._resource_providers = {}

        self.client._ensure_resource_provider(uuids.compute_node,
                                              mock.sentinel.name)

        create_rp_mock.assert_called_once_with(
                uuids.compute_node,
                mock.sentinel.name,
        )

    def test_get_resource_provider_found(self):
        # Ensure _get_resource_provider() returns a ResourceProvider object if
        # it finds a resource provider record from the placement API
        uuid = uuids.compute_node
        resp_mock = mock.Mock(status_code=200)
        json_data = {
            'uuid': uuid,
            'name': uuid,
            'generation': 42,
        }
        resp_mock.json.return_value = json_data
        self.ks_sess_mock.get.return_value = resp_mock

        result = self.client._get_resource_provider(uuid)

        expected_provider = objects.ResourceProvider(
                uuid=uuid,
                name=uuid,
                generation=42,
        )
        expected_url = '/resource_providers/' + uuid
        self.ks_sess_mock.get.assert_called_once_with(expected_url,
                                                      endpoint_filter=mock.ANY,
                                                      raise_exc=False)
        self.assertTrue(obj_base.obj_equal_prims(expected_provider,
                                                 result))

    def test_get_resource_provider_not_found(self):
        # Ensure _get_resource_provider() just returns None when the placement
        # API doesn't find a resource provider matching a UUID
        resp_mock = mock.Mock(status_code=404)
        self.ks_sess_mock.get.return_value = resp_mock

        uuid = uuids.compute_node
        result = self.client._get_resource_provider(uuid)

        expected_url = '/resource_providers/' + uuid
        self.ks_sess_mock.get.assert_called_once_with(expected_url,
                                                      endpoint_filter=mock.ANY,
                                                      raise_exc=False)
        self.assertIsNone(result)

    @mock.patch.object(report.LOG, 'error')
    def test_get_resource_provider_error(self, logging_mock):
        # Ensure _get_resource_provider() sets the error flag when trying to
        # communicate with the placement API and not getting an error we can
        # deal with
        resp_mock = mock.Mock(status_code=503)
        self.ks_sess_mock.get.return_value = resp_mock

        uuid = uuids.compute_node
        result = self.client._get_resource_provider(uuid)

        expected_url = '/resource_providers/' + uuid
        self.ks_sess_mock.get.assert_called_once_with(expected_url,
                                                      endpoint_filter=mock.ANY,
                                                      raise_exc=False)
        # A 503 Service Unavailable should trigger an error logged and
        # return None from _get_resource_provider()
        self.assertTrue(logging_mock.called)
        self.assertIsNone(result)

    def test_create_resource_provider(self):
        # Ensure _create_resource_provider() returns a ResourceProvider object
        # constructed after creating a resource provider record in the
        # placement API
        uuid = uuids.compute_node
        name = 'computehost'
        resp_mock = mock.Mock(status_code=201)
        self.ks_sess_mock.post.return_value = resp_mock

        result = self.client._create_resource_provider(uuid, name)

        expected_payload = {
            'uuid': uuid,
            'name': name,
        }
        expected_provider = objects.ResourceProvider(
            uuid=uuid,
            name=name,
            generation=1,
        )
        expected_url = '/resource_providers'
        self.ks_sess_mock.post.assert_called_once_with(
                expected_url,
                endpoint_filter=mock.ANY,
                json=expected_payload,
                raise_exc=False)
        self.assertTrue(obj_base.obj_equal_prims(expected_provider,
                                                 result))

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_get_resource_provider')
    def test_create_resource_provider_concurrent_create(self, get_rp_mock):
        # Ensure _create_resource_provider() returns a ResourceProvider object
        # gotten from _get_resource_provider() if the call to create the
        # resource provider in the placement API returned a 409 Conflict,
        # indicating another thread concurrently created the resource provider
        # record.
        uuid = uuids.compute_node
        name = 'computehost'
        resp_mock = mock.Mock(status_code=409)
        self.ks_sess_mock.post.return_value = resp_mock

        get_rp_mock.return_value = mock.sentinel.get_rp

        result = self.client._create_resource_provider(uuid, name)

        expected_payload = {
            'uuid': uuid,
            'name': name,
        }
        expected_url = '/resource_providers'
        self.ks_sess_mock.post.assert_called_once_with(
                expected_url,
                endpoint_filter=mock.ANY,
                json=expected_payload,
                raise_exc=False)
        self.assertEqual(mock.sentinel.get_rp, result)

    @mock.patch.object(report.LOG, 'error')
    def test_create_resource_provider_error(self, logging_mock):
        # Ensure _create_resource_provider() sets the error flag when trying to
        # communicate with the placement API and not getting an error we can
        # deal with
        uuid = uuids.compute_node
        name = 'computehost'
        resp_mock = mock.Mock(status_code=503)
        self.ks_sess_mock.post.return_value = resp_mock

        result = self.client._create_resource_provider(uuid, name)

        expected_payload = {
            'uuid': uuid,
            'name': name,
        }
        expected_url = '/resource_providers'
        self.ks_sess_mock.post.assert_called_once_with(
                expected_url,
                endpoint_filter=mock.ANY,
                json=expected_payload,
                raise_exc=False)
        # A 503 Service Unavailable should log an error and
        # _create_resource_provider() should return None
        self.assertTrue(logging_mock.called)
        self.assertIsNone(result)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                '_ensure_resource_provider')
    @mock.patch.object(objects.ComputeNode, 'save')
    def test_update_resource_stats_saves(self, mock_save, mock_ensure):
        cn = objects.ComputeNode(context=self.context,
                                 uuid=uuids.compute_node,
                                 hypervisor_hostname='host1')
        self.client.update_resource_stats(cn)
        mock_save.assert_called_once_with()
        mock_ensure.assert_called_once_with(uuids.compute_node, 'host1')
