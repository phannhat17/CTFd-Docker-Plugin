CTFd.plugin.run((_CTFd) => {
    const $ = _CTFd.lib.$;
    const md = _CTFd.lib.markdown();
    
    // Disable flag modal popup for container challenges
    // Container challenges auto-generate flags based on flag_mode setting
    window.challenge = window.challenge || {};
    window.challenge.data = window.challenge.data || {};
    window.challenge.data.flags = [];
    
    // Override flag creation - container challenges don't need manual flags
    const originalSubmit = window.challenge?.submit;
    if (originalSubmit) {
        window.challenge.submit = function(preview) {
            // Skip flag modal, directly submit
            return originalSubmit.call(this, preview);
        };
    }
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
.then(response => {
    if (!response.ok) {
        return Promise.reject("Error fetching images");
    }
    return response.json();
})
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
    }
})
.catch(error => {
    console.error("Error loading images:", error);
    containerImageDefault.innerHTML = "Error loading images";
});

// Load default settings from config
fetch("/admin/containers/api/config", {
    method: "GET",
    headers: {
        "Accept": "application/json",
        "CSRF-Token": init.csrfNonce
    }
})
.then(response => response.json())
.then(config => {
    // Set default values from global settings
    document.querySelector('input[name="timeout_minutes"]').value = config.default_timeout || 60;
    document.querySelector('input[name="max_renewals"]').value = config.max_renewals || 3;
    document.querySelector('input[name="memory_limit"]').value = config.max_memory || '512m';
    document.querySelector('input[name="cpu_limit"]').value = config.max_cpu || 0.5;
})
.catch(error => {
    console.error("Error loading config:", error);
});
