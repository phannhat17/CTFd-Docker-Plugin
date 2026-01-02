CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$;
    const md = _CTFd.lib.markdown();
    
    // Disable flag modal popup for container challenges
    // Container challenges auto-generate flags based on flag_mode setting
    window.challenge = window.challenge || {};
    window.challenge.data = window.challenge.data || {};
    window.challenge.data.flags = [];
});

// Load Docker images
var containerImage = document.getElementById("container-image");
var containerImageDefault = document.getElementById("container-image-default");

fetch("/admin/containers/api/images", {
    method: "GET",
    headers: {
        "Accept": "application/json",
        "CSRF-Token": init.csrfNonce
    }
})
.then(response => response.json())
.then(data => {
    if (data.error) {
        containerImageDefault.innerHTML = data.error;
    } else {
        for (var i = 0; i < data.images.length; i++) {
            var opt = document.createElement("option");
            opt.value = data.images[i];
            opt.innerHTML = data.images[i];
            containerImage.appendChild(opt);
        }
        containerImageDefault.innerHTML = "Choose an image...";
        containerImage.removeAttribute("disabled");
        
        // Set selected image from challenge data
        if (typeof container_image_selected !== 'undefined') {
            containerImage.value = container_image_selected;
        }
    }
})
.catch(error => {
    console.error("Error loading images:", error);
    containerImageDefault.innerHTML = "Error loading images";
});

// Set connection type value from challenge data
var connectType = document.getElementById("connect-type");
if (connectType && typeof container_connection_type_selected !== 'undefined') {
    connectType.value = container_connection_type_selected;
}
