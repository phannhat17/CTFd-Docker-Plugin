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

function toggleChallengeUpdate() {
    document.getElementById("extend-chal").classList.toggle('d-none');
    document.getElementById("terminate-chal").classList.toggle('d-none');
}

function calculateExpiry(date) {
    return Math.ceil((new Date(date * 1000) - new Date()) / 1000 / 60);
}

function createChallengeLinkElement(data, parent) {
    parent.innerHTML = "";

    let expires = document.createElement('span');
    expires.textContent = "Expires in " + calculateExpiry(new Date(data.expires)) + " minutes.";
    parent.append(expires, document.createElement('br'));

    if (data.connect == "tcp") {
        let codeElement = document.createElement('code');
        codeElement.textContent = 'nc ' + data.hostname + " " + data.port;
        parent.append(codeElement);
    } else if (data.connect == "ssh") {
        let codeElement = document.createElement('code');
        // Support both password-based and key-based SSH authentication
        if (data.ssh_password == null) {
            codeElement.textContent = 'ssh -o StrictHostKeyChecking=no ' + data.ssh_username + '@' + data.hostname + " -p" + data.port;
        } else {
            codeElement.textContent = 'sshpass -p' + data.ssh_password + " ssh -o StrictHostKeyChecking=no " + data.ssh_username + '@' + data.hostname + " -p" + data.port;
        }
        parent.append(codeElement);
    } else if (data.connect == "web-ssh") {
        // Web-SSH: Show HTTP link and SSH credentials
        let link = document.createElement('a');
        link.href = 'http://' + data.hostname + ":" + data.port;
        link.textContent = 'http://' + data.hostname + ":" + data.port;
        link.target = '_blank';
        parent.append(link, document.createElement('br'), document.createElement('br'));

        // SSH Username
        let usernameLabel = document.createElement('strong');
        usernameLabel.textContent = 'SSH Username:';
        parent.append(usernameLabel, document.createElement('br'));

        let usernameContainer = document.createElement('div');
        usernameContainer.style.display = 'flex';
        usernameContainer.style.alignItems = 'center';
        usernameContainer.style.gap = '8px';
        usernameContainer.style.marginBottom = '8px';

        let usernameCode = document.createElement('code');
        usernameCode.textContent = data.ssh_username;
        usernameCode.style.padding = '4px 8px';
        usernameCode.style.backgroundColor = '#f4f4f4';
        usernameCode.style.borderRadius = '4px';
        usernameCode.style.flex = '1';

        let usernameCopyBtn = document.createElement('button');
        usernameCopyBtn.textContent = '📋';
        usernameCopyBtn.className = 'btn btn-sm btn-secondary';
        usernameCopyBtn.title = 'Copy username';
        usernameCopyBtn.onclick = function() {
            navigator.clipboard.writeText(data.ssh_username);
            usernameCopyBtn.textContent = '✓';
            setTimeout(() => { usernameCopyBtn.textContent = '📋'; }, 2000);
        };

        usernameContainer.append(usernameCode, usernameCopyBtn);
        parent.append(usernameContainer);

        // SSH Password (if present)
        if (data.ssh_password) {
            let passwordLabel = document.createElement('strong');
            passwordLabel.textContent = 'SSH Password:';
            parent.append(passwordLabel, document.createElement('br'));

            let passwordContainer = document.createElement('div');
            passwordContainer.style.display = 'flex';
            passwordContainer.style.alignItems = 'center';
            passwordContainer.style.gap = '8px';

            let passwordCode = document.createElement('code');
            passwordCode.textContent = data.ssh_password;
            passwordCode.style.padding = '4px 8px';
            passwordCode.style.backgroundColor = '#f4f4f4';
            passwordCode.style.borderRadius = '4px';
            passwordCode.style.flex = '1';

            let passwordCopyBtn = document.createElement('button');
            passwordCopyBtn.textContent = '📋';
            passwordCopyBtn.className = 'btn btn-sm btn-secondary';
            passwordCopyBtn.title = 'Copy password';
            passwordCopyBtn.onclick = function() {
                navigator.clipboard.writeText(data.ssh_password);
                passwordCopyBtn.textContent = '✓';
                setTimeout(() => { passwordCopyBtn.textContent = '📋'; }, 2000);
            };

            passwordContainer.append(passwordCode, passwordCopyBtn);
            parent.append(passwordContainer);
        }
    } else {
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
        alert.innerHTML = ""; // Remove spinner
        if (data.status == "Challenge not started") {
            alert.innerHTML = data.status;
            toggleChallengeCreate();
        } else if (data.status == "already_running") {
            createChallengeLinkElement(data, alert);
            toggleChallengeUpdate();
        } else {
            alert.innerHTML = data.message;
            alert.classList.add("alert-danger");
            toggleChallengeUpdate();
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
            toggleChallengeUpdate();
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
            alert.innerHTML = "Challenge Terminated.";
            toggleChallengeCreate();
            toggleChallengeUpdate();
        }
    })
    .catch(error => {
        alert.innerHTML = "Error stopping container.";
        alert.classList.add("alert-danger");
        console.error("Fetch error:", error);
    })
    .finally(enableButtons);
}