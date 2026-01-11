CTFd._internal.challenge.data = undefined;
CTFd._internal.challenge.renderer = null;
CTFd._internal.challenge.preRender = function () { };
CTFd._internal.challenge.render = null;
CTFd._internal.challenge.postRender = function () { };

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
    const btn = document.getElementById("create-chal");
    if (btn) {
        btn.classList.remove('d-none');
    }
}

function hideChallengeCreate() {
    const btn = document.getElementById("create-chal");
    if (btn) {
        btn.classList.add('d-none');
    }
}

function toggleChallengeUpdate() {
    const extendBtn = document.getElementById("extend-chal");
    const terminateBtn = document.getElementById("terminate-chal");
    if (extendBtn) extendBtn.classList.remove('d-none');
    if (terminateBtn) terminateBtn.classList.remove('d-none');
}

function hideChallengeUpdate() {
    const extendBtn = document.getElementById("extend-chal");
    const terminateBtn = document.getElementById("terminate-chal");
    if (extendBtn) extendBtn.classList.add('d-none');
    if (terminateBtn) terminateBtn.classList.add('d-none');
}

function calculateExpiry(date) {
    return Math.ceil((new Date(date * 1000) - new Date()) / 1000 / 60);
}

function formatExpiry(timestampMs) {
    const secondsLeft = Math.ceil((timestampMs - Date.now()) / 1000);
    if (secondsLeft < 0) {
        return "Expired";
    } else if (secondsLeft < 60) {
        return "Expires in " + secondsLeft + " seconds";
    } else {
        const minutesLeft = Math.ceil(secondsLeft / 60);
        return "Expires in " + minutesLeft + " minutes";
    }
}

function createChallengeLinkElement(data, parent) {
    parent.innerHTML = "";

    let expires = document.createElement('span');
    expires.textContent = formatExpiry(data.expires_at);
    parent.append(expires, document.createElement('br'));

    if (data.connect == "tcp") {
        let codeElement = document.createElement('code');
        codeElement.textContent = 'nc ' + data.hostname + " " + data.port;
        parent.append(codeElement);
    } else {
        let link = document.createElement('a');
        link.href = 'http://' + data.hostname + ":" + data.port;
        link.textContent = 'http://' + data.hostname + ":" + data.port;
        link.target = '_blank';
        parent.append(link);
    }
}

function view_container_info(challenge_id) {
    // console.log("[Container] Fetching info for challenge", challenge_id);
    let alert = resetAlert();

    fetch("/api/v1/containers/info/" + challenge_id, {
        method: "GET",
        headers: {
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        }
    })
        .then(response => response.json())
        .then(data => {
            // console.log("[Container] Info response:", data);
            alert.innerHTML = ""; // Remove spinner

            if (data.status == "not_found") {
                alert.innerHTML = "No active instance. Click 'Fetch Instance' to start.";
                hideChallengeUpdate();
                toggleChallengeCreate();
            } else if (data.status == "running" || data.status == "provisioning") {
                // Show connection info
                let expires = document.createElement('span');
                expires.textContent = formatExpiry(data.expires_at);
                alert.append(expires, document.createElement('br'));

                // Display connection info based on type
                if (data.connection.type == "tcp" || data.connection.type == "nc") {
                    let codeElement = document.createElement('code');
                    codeElement.textContent = 'nc ' + data.connection.host + " " + data.connection.port;
                    alert.append(codeElement);
                } else if (data.connection.type == "ssh") {
                    let codeElement = document.createElement('code');
                    codeElement.textContent = 'ssh -p ' + data.connection.port + ' user@' + data.connection.host;
                    alert.append(codeElement);
                    if (data.connection.info) {
                        alert.append(document.createElement('br'));
                        let info = document.createElement('small');
                        info.textContent = data.connection.info;
                        alert.append(info);
                    }
                } else if (data.connection.type == "url") {
                    // Subdomain routing - show direct URL
                    let link = document.createElement('a');
                    let url = data.connection.url || ('https://' + data.connection.host);
                    link.href = url;
                    link.textContent = url;
                    link.target = '_blank';
                    alert.append(link);
                    if (data.connection.info) {
                        alert.append(document.createElement('br'));
                        let info = document.createElement('small');
                        info.textContent = data.connection.info;
                        alert.append(info);
                    }
                } else if (data.connection.type == "http" || data.connection.type == "web") {
                    let link = document.createElement('a');
                    link.href = 'http://' + data.connection.host + ":" + data.connection.port;
                    link.textContent = 'http://' + data.connection.host + ":" + data.connection.port;
                    link.target = '_blank';
                    alert.append(link);
                } else if (data.connection.type == "https") {
                    let link = document.createElement('a');
                    link.href = 'https://' + data.connection.host;
                    link.textContent = 'https://' + data.connection.host;
                    link.target = '_blank';
                    alert.append(link);
                } else {
                    // Custom connection type
                    let codeElement = document.createElement('code');
                    codeElement.textContent = data.connection.host + ":" + data.connection.port;
                    alert.append(codeElement);
                    if (data.connection.info) {
                        alert.append(document.createElement('br'));
                        let info = document.createElement('small');
                        info.textContent = data.connection.info;
                        alert.append(info);
                    }
                }
                hideChallengeCreate();
                toggleChallengeUpdate();
            } else {
                alert.innerHTML = data.error || "Unknown status";
                alert.classList.add("alert-danger");
                hideChallengeUpdate();
                toggleChallengeCreate();
            }
        })
        .catch(error => {
            console.error("[Container] Fetch error:", error);
            alert.innerHTML = "Error fetching container info.";
            alert.classList.add("alert-danger");
            toggleChallengeCreate();
        })
        .finally(enableButtons);
}

function container_request(challenge_id) {
    let alert = resetAlert();

    fetch("/api/v1/containers/request", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        },
        body: JSON.stringify({ challenge_id: challenge_id })
    })
        .then(response => response.json())
        .then(data => {
            alert.innerHTML = ""; // Remove spinner
            if (data.error) {
                alert.innerHTML = data.error;
                alert.classList.add("alert-danger");
                toggleChallengeCreate();
            } else {
                // Show connection info
                let expires = document.createElement('span');
                expires.textContent = formatExpiry(data.expires_at);
                alert.append(expires, document.createElement('br'));

                // Display connection info based on type
                if (data.connection.type == "tcp" || data.connection.type == "nc") {
                    let codeElement = document.createElement('code');
                    codeElement.textContent = 'nc ' + data.connection.host + " " + data.connection.port;
                    alert.append(codeElement);
                } else if (data.connection.type == "ssh") {
                    let codeElement = document.createElement('code');
                    codeElement.textContent = 'ssh -p ' + data.connection.port + ' user@' + data.connection.host;
                    alert.append(codeElement);
                    if (data.connection.info) {
                        alert.append(document.createElement('br'));
                        let info = document.createElement('small');
                        info.textContent = data.connection.info;
                        alert.append(info);
                    }
                } else if (data.connection.type == "url") {
                    // Subdomain routing - show direct URL
                    let link = document.createElement('a');
                    let url = data.connection.url || ('https://' + data.connection.host);
                    link.href = url;
                    link.textContent = url;
                    link.target = '_blank';
                    link.className = 'btn btn-sm btn-outline-primary';
                    alert.append(link);
                    if (data.connection.info) {
                        alert.append(document.createElement('br'));
                        let info = document.createElement('small');
                        info.textContent = data.connection.info;
                        alert.append(info);
                    }
                } else if (data.connection.type == "http" || data.connection.type == "web") {
                    let link = document.createElement('a');
                    link.href = 'http://' + data.connection.host + ":" + data.connection.port;
                    link.textContent = 'http://' + data.connection.host + ":" + data.connection.port;
                    link.target = '_blank';
                    alert.append(link);
                } else if (data.connection.type == "https") {
                    let link = document.createElement('a');
                    link.href = 'https://' + data.connection.host;
                    link.textContent = 'https://' + data.connection.host;
                    link.target = '_blank';
                    alert.append(link);
                } else {
                    // Custom connection type
                    let codeElement = document.createElement('code');
                    codeElement.textContent = data.connection.host + ":" + data.connection.port;
                    alert.append(codeElement);
                    if (data.connection.info) {
                        alert.append(document.createElement('br'));
                        let info = document.createElement('small');
                        info.textContent = data.connection.info;
                        alert.append(info);
                    }
                }
                hideChallengeCreate();
                toggleChallengeUpdate();
            }
        })
        .catch(error => {
            console.error("[Container] Request error:", error);
            alert.innerHTML = "Error requesting container.";
            alert.classList.add("alert-danger");
        })
        .finally(enableButtons);
}

function container_renew(challenge_id) {
    let alert = resetAlert();

    fetch("/api/v1/containers/renew", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        },
        body: JSON.stringify({ challenge_id: challenge_id })
    })
        .then(response => response.json())
        .then(data => {
            alert.innerHTML = ""; // Remove spinner
            if (data.error) {
                alert.innerHTML = data.error;
                alert.classList.add("alert-danger");
            } else {
                // Fetch updated info
                view_container_info(challenge_id);
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

    fetch("/api/v1/containers/stop", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        },
        body: JSON.stringify({ challenge_id: challenge_id })
    })
        .then(response => response.json())
        .then(data => {
            alert.innerHTML = ""; // Remove spinner
            if (data.error) {
                alert.innerHTML = data.error;
                alert.classList.add("alert-danger");
            } else {
                alert.innerHTML = "Instance terminated successfully.";
                hideChallengeUpdate();
                toggleChallengeCreate();
            }
        })
        .catch(error => {
            console.error("[Container] Stop error:", error);
            alert.innerHTML = "Error stopping container.";
            alert.classList.add("alert-danger");
        })
        .finally(enableButtons);
}

// Initialize: Inject UI elements if template doesn't load
(function () {
    // console.log("[Container] Initializing - checking for template render");

    let checkCount = 0;
    const maxChecks = 20;

    function checkAndInject() {
        checkCount++;
        // console.log(`[Container] Check #${checkCount}: Looking for deployment-actions or challenge window`);

        // First check if our template loaded
        let deploymentDiv = document.querySelector('.deployment-actions');
        if (deploymentDiv) {
            const challengeId = deploymentDiv.getAttribute('data-challenge-id');
            if (challengeId) {
                // console.log("[Container] Template loaded! Challenge ID:", challengeId);
                view_container_info(parseInt(challengeId));
                return true;
            }
        }

        // If template didn't load, inject UI manually
        const challengeWindow = document.getElementById('challenge-window');
        const challengeBody = challengeWindow ? challengeWindow.querySelector('.modal-body') : null;

        if (challengeBody && !document.querySelector('.deployment-actions-injected')) {
            // console.log("[Container] Template NOT loaded, injecting UI manually");

            // Try multiple ways to get challenge ID
            let challengeId = null;

            // Method 1: From window.challenge
            if (window.challenge?.data?.id) {
                challengeId = window.challenge.data.id;
                // console.log("[Container] Got challenge ID from window.challenge:", challengeId);
            }

            // Method 2: From CTFd internal store
            if (!challengeId && window.CTFd?._internal?.challenge?.data?.id) {
                challengeId = window.CTFd._internal.challenge.data.id;
                // console.log("[Container] Got challenge ID from CTFd._internal:", challengeId);
            }

            // Method 3: From challenge-id input field
            if (!challengeId) {
                const challengeIdInput = document.getElementById('challenge-id');
                if (challengeIdInput) {
                    challengeId = parseInt(challengeIdInput.value);
                    // console.log("[Container] Got challenge ID from input field:", challengeId);
                }
            }

            // Method 4: From modal title or data attributes
            if (!challengeId && challengeWindow) {
                const titleElement = challengeWindow.querySelector('[data-challenge-id]');
                if (titleElement) {
                    challengeId = parseInt(titleElement.getAttribute('data-challenge-id'));
                    // console.log("[Container] Got challenge ID from data attribute:", challengeId);
                }
            }

            if (!challengeId) {
                console.warn("[Container] Cannot get challenge ID, available data:", {
                    'window.challenge': window.challenge,
                    'CTFd._internal.challenge': window.CTFd?._internal?.challenge,
                    'challenge-id input': document.getElementById('challenge-id')?.value
                });
                return false;
            }

            // console.log("[Container] Using challenge ID:", challengeId);

            // Create container UI
            const containerDiv = document.createElement('div');
            containerDiv.className = 'mb-3 text-center deployment-actions-injected';
            containerDiv.innerHTML = `
                <div class="alert alert-primary" id="deployment-info">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                </div>
                <span>
                    <button onclick="container_request(${challengeId})" class="btn btn-primary d-none" id="create-chal">
                        <small style="color: white"> Fetch Instance </small>
                    </button>
                    <button onclick="container_renew(${challengeId})" class="btn btn-info d-none" id="extend-chal">
                        <small style="color: white"> Extend Time </small>
                    </button>
                    <button onclick="container_stop(${challengeId})" class="btn btn-danger d-none" id="terminate-chal">
                        <small style="color: white"> Terminate </small>
                    </button>
                </span>
            `;

            // Insert after challenge description
            const descSection = challengeBody.querySelector('.challenge-desc');
            if (descSection) {
                descSection.after(containerDiv);
                // console.log("[Container] UI injected, calling view_container_info");
                view_container_info(challengeId);
                return true;
            } else {
                challengeBody.insertBefore(containerDiv, challengeBody.firstChild);
                // console.log("[Container] UI injected at top, calling view_container_info");
                view_container_info(challengeId);
                return true;
            }
        }

        if (checkCount >= maxChecks) {
            console.error("[Container] Max checks reached, giving up");
            return true; // Stop checking
        }

        return false;
    }

    // Try immediately
    if (checkAndInject()) return;

    // Watch for changes
    const observer = new MutationObserver(function (mutations) {
        if (checkAndInject()) {
            observer.disconnect();
        }
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    // console.log("[Container] MutationObserver started");
})();