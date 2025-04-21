CTFd._internal.challenge.data = undefined;
CTFd._internal.challenge.renderer = null;
CTFd._internal.challenge.preRender = function () {};
CTFd._internal.challenge.render = null;
CTFd._internal.challenge.postRender = function () {};

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
            if (response.status === 429) return response; // Rate limit
            if (response.status === 403) return response; // Not logged in / CTF paused
            return response;
        });
};

function mergeQueryParams(parameters, queryParameters) {
    if (parameters.$queryParameters) {
        Object.keys(parameters.$queryParameters).forEach(function (parameterName) {
            queryParameters[parameterName] = parameters.$queryParameters[parameterName];
        });
    }
    return queryParameters;
}

function resetAlert() {
    let alert = document.getElementById("deployment-info");
    alert.innerHTML = '<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div>';
    alert.classList.remove("alert-danger");

    // Disable buttons while loading
    document.getElementById("create-chal").disabled = true;
    document.getElementById("extend-chal").disabled = true;
    document.getElementById("terminate-chal").disabled = true;

    return alert;
}

function enableButtons() {
    document.getElementById("create-chal").disabled = false;
    document.getElementById("extend-chal").disabled = false;
    document.getElementById("terminate-chal").disabled = false;
}

function toggleChallengeCreate() {
    document.getElementById("create-chal").classList.toggle('d-none');
}

function toggleChallengeUpdate(isInfinite, removeTerminate = false) {
    const extendBtn = document.getElementById("extend-chal");
    const terminateBtn = document.getElementById("terminate-chal");
    if (removeTerminate) {
        terminateBtn.classList.add('d-none');
    }
    else{
        terminateBtn.classList.remove('d-none');
    }
    
    if (isInfinite) {
        extendBtn.classList.add('d-none');
    } else {
        extendBtn.classList.remove('d-none');
    }
}

function calculateExpiry(date) {
    return Math.ceil((new Date(date * 1000) - new Date()) / 1000 / 60);;
}

function createChallengeLinkElement(data, parent) {
    parent.innerHTML = "";

    let expires = document.createElement('span');
    if(data.container_expiration != 0){
        expires.textContent = "Expires in " + calculateExpiry(new Date(data.expires)) + " minutes.";
        parent.append(expires, document.createElement('br'));
    }else{
        expires.textContent = "No expiration instance limit.";
        parent.append(expires, document.createElement('br'));
    }

    if (data.connect == "tcp") {
        let codeElement = document.createElement('code');
        codeElement.textContent = 'nc ' + data.hostname + " " + data.port;
        parent.append(codeElement);
    }else if(data.connect == 'ssh'){
        let ssh = document.createElement('code');
        ssh.textContent = 'ssh ' + data.username + "@" + data.hostname + ' -p '  + data.port;
        let passwordDisplay = document.createElement('code');
        passwordDisplay.textContent = 'Password: ' + data.password;
        parent.append(ssh)
        parent.append(document.createElement('br'));
        parent.append(passwordDisplay);
    }
     else {
        let link = document.createElement('a');
        link.href = 'http://' + data.hostname + ":" + data.port;
        link.textContent = 'http://' + data.hostname + ":" + data.port;
        link.target = '_blank';
        parent.append(link);
    }
}


function view_container_info(challenge_id) {
    let alert = resetAlert();

    fetch("/containers/api/view_info", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        },
        body: JSON.stringify({ chal_id: challenge_id })
    })
    .then(response => response.json())
    .then(data => {
        alert.innerHTML = "";
        if (data.status == "Challenge not started") {
            alert.innerHTML = data.status;
            toggleChallengeCreate();
        } else if (data.status == "already_running") {
            isInfinite = data.container_expiration == 0;
            createChallengeLinkElement(data, alert);
            toggleChallengeUpdate(isInfinite);
        } else {
            alert.innerHTML = data.message;
            alert.classList.add("alert-danger");
            isInfinite = data.container_expiration == 0;
            toggleChallengeUpdate(isInfinite);
        }
    })
    .catch(error => {
        alert.innerHTML = "Error fetching container info.";
        alert.classList.add("alert-danger");
        console.error("Fetch error:", error);
    })
    .finally(enableButtons);
}

function container_request(challenge_id) {
    let alert = resetAlert();

    fetch("/containers/api/request", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        },
        body: JSON.stringify({ chal_id: challenge_id })
    })
    .then(response => response.json())
    .then(data => {
        alert.innerHTML = ""; // Remove spinner
        if (data.error) {
            alert.innerHTML = data.error;
            alert.classList.add("alert-danger");
            toggleChallengeCreate();
        } else if (data.message) {
            alert.innerHTML = data.message;
            alert.classList.add("alert-danger");
            toggleChallengeCreate();
        } else {
            createChallengeLinkElement(data, alert);
            isInfinite = data.container_expiration == 0;
            toggleChallengeUpdate(isInfinite);
            toggleChallengeCreate();
        }
    })
    .catch(error => {
        alert.innerHTML = "Error requesting container.";
        alert.classList.add("alert-danger");
        console.error("Fetch error:", error);
    })
    .finally(enableButtons);
}

function container_renew(challenge_id) {
    let alert = resetAlert();

    fetch("/containers/api/renew", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        },
        body: JSON.stringify({ chal_id: challenge_id })
    })
    .then(response => response.json())
    .then(data => {
        alert.innerHTML = ""; // Remove spinner
        if (data.error) {
            alert.innerHTML = data.error;
            alert.classList.add("alert-danger");
        } else if (data.message) {
            alert.innerHTML = data.message;
            alert.classList.add("alert-danger");
        } else {
            createChallengeLinkElement(data, alert);
        }
    })
    .catch(error => {
        alert.innerHTML = "Error renewing container.";
        alert.classList.add("alert-danger");
        console.error("Fetch error:", error);
    })
    .finally(enableButtons);
}

function container_stop(challenge_id) {
    let alert = resetAlert();

    fetch("/containers/api/stop", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        },
        body: JSON.stringify({ chal_id: challenge_id })
    })
    .then(response => response.json())
    .then(data => {
        alert.innerHTML = "";
        if (data.error) {
            alert.innerHTML = data.error;
            alert.classList.add("alert-danger");
            toggleChallengeCreate();
        } else if (data.message) {
            alert.innerHTML = data.message;
            alert.classList.add("alert-danger");
            toggleChallengeCreate();
        } else {
            alert.innerHTML = "Challenge Terminated.";
            toggleChallengeCreate();
            toggleChallengeUpdate(true, true);
        }
    })
    .catch(error => {
        alert.innerHTML = "Error stopping container.";
        alert.classList.add("alert-danger");
        console.error("Fetch error:", error);
    })
    .finally(enableButtons);
}