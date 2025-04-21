CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$;
    const md = _CTFd.lib.markdown();
    
});

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
.then(response => {
    if (!response.ok) {
        // Handle error response
        return Promise.reject("Error fetching data");
    }
    return response.json();
})
.then(data => {
    if (data.error != undefined) {
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
    }
    console.log(data);
})
.catch(error => {
    // Handle fetch error
    console.error(error);
});
