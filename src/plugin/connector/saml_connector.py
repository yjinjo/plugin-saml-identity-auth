import logging
import xml.etree.ElementTree as ET
from typing import Tuple

import requests
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from spaceone.core.connector import BaseConnector
from spaceone.core.error import ERROR_AUTHENTICATE_FAILURE, ERROR_NOT_FOUND

_LOGGER = logging.getLogger(__name__)


class SamlConnector(BaseConnector):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saml_settings = {}

    def init(self, options: dict) -> dict:
        """Checks the connection using the SAML metadata URL.

        Args:
            options: 'dict'
              'protocol': 'str',
              'identity_provider': 'str',
              'icon': 'str',
              'metadata_url': 'str',

        Returns:
            'metadata': 'dict'
        """

        protocol = options.get("protocol", "saml")
        identity_provider = options.get("identity_provider")
        icon = options.get("icon")
        metadata_url = options.get("metadata_url")

        xml_data = self._fetch_xml(metadata_url)
        _, _, sso_url = self._parse_idp_xml(xml_data)

        idp_name = self._get_idp_name(identity_provider)

        metadata = {
            "identity_provider": identity_provider,
            "protocol": protocol,
            "icon": icon,
            "idp_name": idp_name,
            "sso_url": sso_url,
        }

        return metadata

    def authorize(self, params: dict, metadata_url: str, domain_id: str) -> dict:
        """Authorizes the user using SAML.

        Args:
            'params': 'dict',
            'metadata_url': 'str',
            'domain_id': 'str',

        Returns:
            'user_info': 'dict'

        Raises:
            ERROR_AUTHENTICATE_FAILURE: If authentication fails
        """
        self._set_saml_settings(params, metadata_url, domain_id)

        auth = OneLogin_Saml2_Auth(
            params,
            self.saml_settings,
        )
        auth.process_response()

        errors = auth.get_errors()
        if not errors and auth.is_authenticated():
            user_info = self._get_user_info_from_auth(auth)
            return user_info

        _LOGGER.error(
            f"[authorize] ERROR_AUTHENTICATE_FAILURE: {errors}",
        )
        raise ERROR_AUTHENTICATE_FAILURE(
            message=f"ERROR_AUTHENTICATE_FAILURE: {errors}"
        )

    @staticmethod
    def _get_user_info_from_auth(auth: OneLogin_Saml2_Auth) -> dict:
        """Extracts user information from the SAML authentication response.

        Args:
            'auth': 'OneLogin_Saml2_Auth'

        Returns:
            'user_info': 'dict'
                'user_id': 'str'
        """

        try:
            name_id = auth.get_nameid()

            user_info = {"user_id": name_id}

            return user_info
        except Exception as e:
            _LOGGER.error(f"[_get_user_info_from_auth] ERROR_NOT_FOUND: {e}")
            raise ERROR_NOT_FOUND(message=f"ERROR_NOT_FOUND: {e}")

    def _set_saml_settings(
        self,
        params: dict,
        metadata_url: str,
        domain_id: str,
    ) -> None:
        """Sets the SAML settings using the metadata URL and domain ID.

        Args:
            'params': 'dict',
            'metadata_url': 'str',
            'sp_metadata_url': 'str',
            'domain_id': 'str',
        """
        idp_xml_data = self._fetch_xml(metadata_url)
        entity_id, idp_x509_certificate, sso_url = self._parse_idp_xml(idp_xml_data)

        http_host = params.get("http_host")
        acs_url = f"https://{http_host}/console-api/extension/auth/saml/{domain_id}"

        self.saml_settings = {
            "strict": True,
            "debug": True,
            "idp": {
                "entityId": entity_id,
                "singleSignOnService": {
                    "url": sso_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                },
                "x509cert": idp_x509_certificate,
            },
            "sp": {
                "entityId": domain_id,
                "assertionConsumerService": {
                    "url": acs_url,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                },
                # "x509cert": sp_x509_certificate,
            },
            "security": {
                "wantAssertionsSigned": True,
                "wantNameId": True,
                "wantAttributeStatement": False,
            },
        }

    @staticmethod
    def _fetch_xml(metadata_url: str) -> bytes:
        """Fetches the XML data from the metadata URL.

        Args:
            'metadata_url': 'str'

        Returns:
            'xml': 'bytes'

        Raises:
            ERROR_NOT_FOUND: If the metadata URL is not found
        """
        try:
            response = requests.get(metadata_url)
            response.raise_for_status()
            return response.content
        except Exception as e:
            _LOGGER.error(f"[init] ERROR_NOT_FOUND: {e}")
            raise ERROR_NOT_FOUND(message=f"ERROR_NOT_FOUND: {e}")

    @staticmethod
    def _parse_idp_xml(xml_data: bytes) -> Tuple[str, str, str]:
        """Parses the XML data to extract entity ID, x509 certificate, and SSO URL.

        Args:
            'xml_data': 'bytes'

        Returns:
            ('entity_id': 'str', 'x509_certificate': 'str', 'sso_url': 'str'): 'tuple'
        """
        root = ET.fromstring(xml_data)

        ns = {
            "md": "urn:oasis:names:tc:SAML:2.0:metadata",
            "ds": "http://www.w3.org/2000/09/xmldsig#",
        }

        entity_id = root.attrib["entityID"]
        x509_certificate = root.find(".//ds:X509Certificate", ns).text

        sso_service = root.find(".//md:SingleSignOnService", ns)

        sso_url = None
        if sso_service is not None:
            sso_url = sso_service.attrib["Location"]

        return entity_id, x509_certificate, sso_url

    @staticmethod
    def _get_idp_name(identity_provider: str) -> str:
        """Generates a name for the identity provider.

        Args:
            'identity_provider': 'str'

        Returns:
            'idp_name': 'str'
        """
        idp_name = {
            "okta": "Okta",
            "frontegg": "Frontegg",
            "auth0": "Auth0",
            "one_login": "OneLogin",
            "pops": "Megazone PoPs",
            "ping_identity": "Ping Identity",
            "workos": "WorkOS",
            "keycloak": "Keycloak",
            "microsoft_entra_id": "Microsoft Entra ID",
        }
        idp_name = idp_name.get(identity_provider, identity_provider.capitalize())

        return idp_name
