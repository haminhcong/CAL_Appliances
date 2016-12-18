import crypt
import json

from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from management.models import Provider, Network, App
from django.views.decorators.http import require_POST
from django.shortcuts import redirect
from django.http import HttpResponse
from calplus import provider as calplus_provider, client


def format_config(dd, level=0):
    """
    Support convert dict into html ul li tags
    :param dictObj:
    :param parent:
    :param indent:
    :return:

    E.G.: _printItems(dictObj, 'root', 0)
    """
    text = '<ul>'
    for k, v in dd.iteritems():
        text += '&nbsp;' * (4 * level) + \
                '<li>%s: &nbsp;</li> %s' % (k, format_config(v, level + 1) if isinstance(v, dict) else (
                    json.dumps(v) if isinstance(v, list) else v))

    text += '</ul>'

    return text

def format_userdata(image, script):
    userdata="""#!/bin/bash
    docker pull {}
    docker run -d {} {}'
    """.format(image, image, script)
    return userdata


def delete_pass(config):
    """ This is so stupid and temporary function
    """
    try:
        del config['os_password']
        del config['aws_secret_access_key']
    except Exception as e:
        pass


class AppView(LoginRequiredMixin, TemplateView):
    login_url = '/auth/login/'
    template_name = 'management/app.html'

    def get(self, request, *args, **kwargs):
        first_name = request.user.first_name
        last_name = request.user.last_name
        full_name = " ".join([first_name, last_name])
        providers = Provider.objects.filter(user_id=request.user.id)

        list_provider_id = []
        for provider in providers:
            list_provider_id.append(provider.id)

        apps = App.objects.filter(provider_id__in=list_provider_id)
        for app in apps:
            setattr(app, 'config', format_config(
                {
                    'Docker Image': app.docker_image,
                    'Ports: ': app.ports
                }
            ))

        return self.render_to_response({
            'fullname': full_name,
            'apps': apps
        })

    def post(self, request, *args, **kwargs):
        """
        Action: create, edit, make network connect to external and delete network
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        id = request.POST.get('id')
        if id:
            # Get an exist provider
            app = App.objects.get(id=id)
            app.name = request.POST.get('name')
            app.ports = request.POST.get('ports')
            app.start_script = request.POST.get('start-script')
        else:
            # Crete provider
            app = App()

            # DATABASE
            app.name = request.POST.get('name')
            app.ports = request.POST.get('ports')
            app.start_script = request.POST.get('start-script')
            # Dont accept for change docker_image and network_id at this time
            # TODO: may be, we will support change network_id in future
            app.docker_image = request.POST.get('docker-image')
            app.network_id = request.POST.get('network-id')
            app.provider_id = request.POST.get('provider-id')

            # ON CLOUD
            provider = Provider.objects.get(id=app.provider_id)
            p = calplus_provider.Provider(provider.type,
                dict(json.loads(provider.config)))
            compute_client = client.Client(version='1.0.0',
                            resource='compute',
                            provider=p
                            )
            network_client = client.Client(version='1.0.0',
                            resource='network',
                            provider=p
                            )
            real_network_id_ops = network_client.show(app.network_id).get('network_id')
            compute_client.create(
                '2f6026a3-4a40-4a6d-a6c8-28860fc63555', #image Ubuntu Docker
                '2', # Flavor
                real_network_id_ops, # 
                None, 1,  # need two by lossing add default in base class
                userdata=format_userdata(app.docker_image, app.start_script))

        app.save()

        return self.get(request)


class NetworkView(LoginRequiredMixin, TemplateView):
    login_url = '/auth/login/'
    template_name = 'management/network.html'

    def get(self, request, *args, **kwargs):
        first_name = request.user.first_name
        last_name = request.user.last_name
        full_name = " ".join([first_name, last_name])
        providers = Provider.objects.filter(user_id=request.user.id)

        list_provider_id = []
        for provider in providers:
            list_provider_id.append(provider.id)

        networks = Network.objects.filter(provider_id__in=list_provider_id)

        provider_name_dict = {}
        provider_config_dict = {}

        for provider in providers:
            provider_name_dict[provider.id] = provider.name

        for provider in providers:
            provider_config_dict[provider.id] = \
                dict(json.loads(provider.config))

        for network in networks:
            config = provider_config_dict.get(network.provider_id)
            delete_pass(config)
            setattr(network, 'provider_config', format_config(
                    config
                )
            )
            setattr(network, 'provider_name',
                provider_name_dict.get(network.provider_id))

        return self.render_to_response({
            'fullname': full_name,
            'networks': networks
        })

    def post(self, request, *args, **kwargs):
        """
        Action: create, edit, make network connect to external and delete network
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        id = request.POST.get('id')
        check_enable = request.POST.get('check-enable')
        check = request.POST.get('check')

        if id:
            # Get exist network
            network = Network.objects.get(id=id)
            network.name = request.POST.get('name')
        else:
            # Crete provider
            network = Network()
            # Dont accept change provider_id
            network.provider_id = request.POST.get('provider-id')
            network.name = request.POST.get('name')
            network.cidr = request.POST.get('cidr')
            provider = Provider.objects.get(id=network.provider_id)
            p = calplus_provider.Provider(provider.type,
                dict(json.loads(provider.config)))
            try:
                network_client = client.Client(version='1.0.0',
                                        resource='network',
                                        provider=p
                                    )
                net = network_client.create(network.name, network.cidr)
                network_client.connect_external_net(net.get('id'))
                network.network_id = net.get('id')
            except Exception as e:
                raise e

        network.save()
        return self.get(request)


class ProviderView(LoginRequiredMixin, TemplateView):
    login_url = '/auth/login/'
    template_name = 'management/provider.html'
    cloud_config = {
        # this keyword must to match with type in model
        'openstack': [
            'os_project_domain_name',
            'os_user_domain_name',
            'os_project_name',
            'os_username',
            'os_password',
            'os_auth_url'
        ],
        'amazon': [
            'aws_access_key_id',
            'aws_secret_access_key',
            'region_name',
            'endpoint_url'
        ]
    }

    def _provider_to_tuple(self, providers):
        """
        Convert provider object list to list of tupbles
        :param providers:
        :return:
        """
        items = []
        for provider in providers:
            id = provider.id
            name = provider.name

            config = dict(json.loads(provider.config))
            delete_pass(config)
            format = format_config(config)
            config['format'] = format

            enable = provider.enable
            type = provider.type
            items.append((id, name, config, enable, type))

        return items

    def _get_provider_config(self, request):
        """
        Get provider config when create or delete and push into dict
        :param request:
        :return:
        """
        cloud_type = request.POST.get('cloud')
        config_dict = {}
        if cloud_type:
            for attr in self.cloud_config.get(cloud_type):
                config_dict[attr] = request.POST.get(attr)

        return config_dict

    def get(self, request, *args, **kwargs):
        first_name = request.user.first_name
        last_name = request.user.last_name
        full_name = " ".join([first_name, last_name])
        providers = Provider.objects.filter(user_id=request.user.id)

        return self.render_to_response({
            'fullname': full_name,
            'table': self._provider_to_tuple(providers)
        })

    def post(self, request, *args, **kwargs):
        """
        We have 3 case in this function: create, edit and change enable/disable
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        id = request.POST.get('id')
        check_enable = request.POST.get('check-enable')
        check = request.POST.get('check')

        if id:
            # Get or enable/disable exist provider
            provider = Provider.objects.get(id=id)
            if check_enable:
                # Enable/disable
                if check:
                    provider.enable = 1
                else:
                    provider.enable = 0
                provider.save()
                return self.get(request)
        else:
            # Crete provider
            provider = Provider()
            # secret = request.POST.get('secret')
            # provider.secret = crypt.crypt(secret.encode('utf-8'), '$11$' + 'salt1234')

        provider.name = request.POST.get('name')
        provider.config = json.dumps(
            self._get_provider_config(request)
        )
        provider.type = request.POST.get('cloud')
        provider.user_id = request.user.id
        provider.save()

        return self.get(request)


class AboutView(LoginRequiredMixin, TemplateView):
    template_name = 'management/about.html'

    def get(self, request, *args, **kwargs):
        return self.render_to_response({})


@require_POST
def delete_provider(request):
    id = request.POST.get('id')
    if id:
        Provider.objects.filter(id=id).delete()

    return redirect("/provider")


@login_required(login_url='/auth/login/')
def list_provider(request):
    providers = Provider.objects.filter(user_id=request.user.id, enable=1)
    response = ""
    for provider in providers:
        response += "<option value='{}'>{}</option>" .format(provider.id, provider.name)

    return HttpResponse(response)


@require_POST
def delete_network(request):
    id = request.POST.get('id')
    if id:
        Network.objects.filter(id=id).delete()

    return redirect("/network")


@login_required(login_url='/auth/login/')
def list_network(request):
    provider_id = request.GET.get('provider_id')
    networks = Network.objects.filter(provider_id=provider_id)
    response = ""
    for network in networks:
        response += "<option value='{}'>{}</option>" .format(network.network_id, network.name)

    return HttpResponse(response)


@require_POST
def delete_app(request):
    id = request.POST.get('id')
    if id:
        App.objects.filter(id=id).delete()

    return redirect("/app")

@require_POST
def migrate_app(request):
    return HttpResponse("Say hello")

# @require_POST
# def change_secret(request):
#     id = request.POST.get('id')
#     old_secret = request.GET.get('old_secret')
#     new_secret = request.GET.get('new_secret')
#     if id:
#         provider = Provider.objects.get(id=id)
#         if crypt.crypt(old_secret.encode('utf-8'), '$11$' + 'salt1234') == provider.secret:
#             provider.secret = crypt.crypt(new_secret.encode('utf-8'), '$11$' + 'salt1234')
#         else:
#             # TODO: redirect + notif
#             pass

#     return redirect("/provider")