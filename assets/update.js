var containerImage = document.getElementById("container-image");
var containerImageDefault = document.getElementById("container-image-default");
var path = "/containers/admin/api/images";

function toggleSSHInputs() {
    const connectionType = document.getElementById("connect-type").value;
    const usernameInput = document.getElementById("ssh-username");
    const passwordInput = document.getElementById("ssh-password");

    const shouldEnable = (connectionType === "ssh");

    usernameInput.disabled = !shouldEnable;
    usernameInput.required = shouldEnable;
    if (!shouldEnable) usernameInput.value = "";

    passwordInput.disabled = !shouldEnable;
    passwordInput.required = shouldEnable;
    if (!shouldEnable) passwordInput.value = "";
}

document.addEventListener("DOMContentLoaded", () => {
    toggleSSHInputs();
    const connectTypeSelect = document.getElementById("connect-type");
    if (connectTypeSelect) {
        connectTypeSelect.addEventListener("change", toggleSSHInputs);
    }
});

fetch(path, {
    method: "GET",
    headers: {
        "Accept": "application/json",
        "CSRF-Token": init.csrfNonce
    }
})
    .then(response => response.json())
    .then(data => {
        if (data.error !== undefined) {
            // Error
            containerImageDefault.innerHTML = data.error;
        } else {
            // Success
            for (var i = 0; i < data.images.length; i++) {
                var opt = document.createElement("option");
                opt.value = data.images[i];
                opt.innerHTML = data.images[i];
                containerImage.appendChild(opt);
            }
            containerImageDefault.innerHTML = "Choose an image...";
            containerImage.removeAttribute("disabled");
            containerImage.value = container_image_selected;
        }
        console.log(data);
    })
    .catch(error => {
        console.error("Fetch error:", error);
    });

var currentURL = window.location.href;
var match = currentURL.match(/\/challenges\/(\d+)/);

if (match && match[1]) {
    var challenge_id = parseInt(match[1]);

    var connectType = document.getElementById("connect-type");
    var connectTypeDefault = document.getElementById("connect-type-default");

    var connectTypeEndpoint = "/containers/api/get_connect_type/" + challenge_id;

    fetch(connectTypeEndpoint, {
        method: "GET",
        headers: {
            "Accept": "application/json",
            "CSRF-Token": init.csrfNonce
        }
    })
        .then(response => response.json())
        .then(connectTypeData => {
            if (connectTypeData.error !== undefined) {
                console.error("Error:", connectTypeData.error);
            } else {
                var connectTypeValue = connectTypeData.connect;

                connectTypeDefault.innerHTML = "Choose...";
                connectType.removeAttribute("disabled");
                connectType.value = connectTypeValue;
            }
            console.log(connectTypeData);
        })
        .catch(error => {
            console.error("Fetch error:", error);
        });
} else {
    console.error("Challenge ID not found in the URL.");
}
