import Keycloak from 'keycloak-js';

// Keycloak server config (26.3.2)
const keycloak = new Keycloak({
    url: 'http://localhost:8080/',
    //url: 'http://keycloak.localtest.me:8080/',
    //url: 'http://host.docker.internal:8080/',
    realm: 'satishrealm',
    clientId: 'testclient',
});

export default keycloak;
