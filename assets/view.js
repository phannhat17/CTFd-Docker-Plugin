CTFd._internal.challenge.data = undefined;

CTFd._internal.challenge.renderer = null;

CTFd._internal.challenge.preRender = function () {
};

CTFd._internal.challenge.render = null;

CTFd._internal.challenge.postRender = function () {
};

CTFd._internal.challenge.submit = function (preview) {
    var challenge_id = parseInt(CTFd.lib.$("#challenge-id").val());
    var submission = CTFd.lib.$("#challenge-input").val();

    let alert = resetAlert();

    var body = {
        challenge_id: challenge_id,
        submission: submission,
    };
    var params = {};
    if (preview) {
        params["preview"] = true;
    }

    return CTFd.api
        .post_challenge_attempt(params, body)
        .then(function (response) {
            if (response.status === 429) {
                // User was ratelimited but process response
                return response;
            }
            if (response.status === 403) {
                // User is not logged in or CTF is paused.
                return response;
            }
            return response;
        });
};

function mergeQueryParams(parameters, queryParameters) {
    if (parameters.$queryParameters) {
        Object.keys(parameters.$queryParameters).forEach(function (
            parameterName
        ) {
            var parameter = parameters.$queryParameters[parameterName];
            queryParameters[parameterName] = parameter;
        });
    }

    return queryParameters;
}

function resetAlert() {
    let alert = document.getElementById("deployment-info");
    alert.innerHTML = "";
    alert.classList.remove("alert-danger");
    return alert;
}

function toggleChallengeCreate() {
    let btn = document.getElementById("create-chal");
    btn.classList.toggle('d-none');
}

function toggleChallengeUpdate() {
    let btn = document.getElementById("extend-chal");
    btn.classList.toggle('d-none');

    btn = document.getElementById("terminate-chal");
    btn.classList.toggle('d-none');
}

function calculateExpiry(date) {
    // Get the difference in minutes
    let difference = Math.ceil(
        (new Date(date * 1000) - new Date()) / 1000 / 60
    );
    ;
    return difference;
}

function createChallengeLinkElement(data, parent) {

    var expires = document.createElement('span');
    expires.textContent = "Expires in " + calculateExpiry(new Date(data.expires)) + " minutes.";

    parent.append(expires);
    parent.append(document.createElement('br'));

    if (data.connect === "tcp") {
        let codeElement = document.createElement('code');
        codeElement.textContent = 'nc ' + data.hostname + " " + data.port;
        parent.append(codeElement);
    } else if (data.connect === "ssh") {
        let codeElement = document.createElement('code');
        codeElement.textContent = 'ssh [user]@' + data.hostname + " -p" + data.port;
        parent.append(codeElement);
    } else {
        let link = document.createElement('a');
        link.href = 'http://' + data.hostname + ":" + data.port;
        link.textContent = 'http://' + data.hostname + ":" + data.port;
        link.target = '_blank'
        parent.append(link);
    }
}

function view_container_info(challenge_id) {
    resetAlert();
    var path = "/containers/api/view_info";

    let alert = document.getElementById("deployment-info");
    fetch(path, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        },
        body: JSON.stringify({chal_id: challenge_id})
    })
        .then(response => response.json())
        .then(data => {
            if (data.status == "Challenge not started") {
                alert.append(data.status);
                toggleChallengeCreate();
            } else if (data.status == "already_running") {
                // Success
                createChallengeLinkElement(data, alert);
                toggleChallengeUpdate();
                console.log(data);
            } else {
                resetAlert();
                alert.append(data.message);
                alert.classList.toggle('alert-danger');
                toggleChallengeUpdate();
                console.log(data);
            }
        })
        .catch(error => {
            console.error("Fetch error:", error);
        });
}

function container_request(challenge_id) {
    var path = "/containers/api/request";
    let alert = resetAlert();

    fetch(path, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        },
        body: JSON.stringify({chal_id: challenge_id})
    })
        .then(response => response.json())
        .then(data => {
            if (data.error !== undefined) {
                // Container error
                alert.append(data.error);
                alert.classList.toggle('alert-danger');
                toggleChallengeCreate();
            } else if (data.message !== undefined) {
                // CTFd error
                alert.append(data.message);
                alert.classList.toggle('alert-danger');
                toggleChallengeCreate();
            } else {
                // Success
                createChallengeLinkElement(data, alert);
                toggleChallengeUpdate();
                toggleChallengeCreate();
            }
            console.log(data);
        })
        .catch(error => {
            console.error("Fetch error:", error);
        });
}

function container_renew(challenge_id) {
    var path = "/containers/api/renew";
    let alert = resetAlert();

    fetch(path, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        },
        body: JSON.stringify({chal_id: challenge_id})
    })
        .then(response => response.json())
        .then(data => {
            if (data.error !== undefined) {
                // Container error
                alert.append(data.error);
                alert.classList.toggle('alert-danger');
                toggleChallengeCreate();
            } else if (data.message !== undefined) {
                // CTFd error
                alert.append(data.message);
                alert.classList.toggle('alert-danger');
                toggleChallengeCreate();
            } else {
                // Success
                createChallengeLinkElement(data, alert);
            }
            console.log(data);
        })
        .catch(error => {
            console.error("Fetch error:", error);
        });
}

function container_stop(challenge_id) {
    var path = "/containers/api/stop";
    let alert = resetAlert();

    fetch(path, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        },
        body: JSON.stringify({chal_id: challenge_id})
    })
        .then(response => response.json())
        .then(data => {
            if (data.error !== undefined) {
                // Container error
                alert.append(data.error);
                alert.classList.toggle('alert-danger');
                toggleChallengeCreate();
            } else if (data.message !== undefined) {
                // CTFd error
                alert.append(data.message);
                alert.classList.toggle('alert-danger');
                toggleChallengeCreate();
            } else {
                // Success
                alert.append("Challenge Terminated.");
                toggleChallengeCreate();
                toggleChallengeUpdate();
            }
            console.log(data);
        })
        .catch(error => {
            console.error("Fetch error:", error);
        });
}

