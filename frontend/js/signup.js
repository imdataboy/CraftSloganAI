document.querySelector('form').addEventListener('submit', function (event) {
    event.preventDefault(); // Prevent page refresh

    // Get user inputs
    const fullName = document.querySelector('input[placeholder="Full Name"]').value;
    const email = document.querySelector('input[placeholder="Email Address"]').value;
    const password = document.querySelector('input[placeholder="Password"]').value;
    const confirmPassword = document.querySelector('input[placeholder="Confirm Password"]').value;


    fetch(new URL('/signup', window.API_BASE), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            full_name: fullName,
            email: email,
            password: password,
            confirm_password: confirmPassword,
        }),
    })
        .then(response => {
            console.log('Response status:', response.status);
            return response.json();
        })
        .then(data => {
            // Create a message box
            const messageBox = document.createElement('div');
            messageBox.style.position = 'fixed';
            messageBox.style.bottom = '20px';
            messageBox.style.right = '20px';
            messageBox.style.padding = '15px 30px';
            messageBox.style.color = '#fff';
            messageBox.style.backgroundColor = data.error ? '#e74c3c' : '#2ecc71'; // Red for error, green for success
            messageBox.style.borderRadius = '8px';
            messageBox.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.2)';
            messageBox.style.opacity = '1';
            messageBox.style.transition = 'opacity 0.5s ease';
            messageBox.textContent = data.error ? `Error: ${data.error}` : `Success: ${data.message}`;

            document.body.appendChild(messageBox);

            // Redirect on success
            setTimeout(() => {
                messageBox.style.opacity = '0';
                setTimeout(() => messageBox.remove(), 500);
                if (!data.error) {
                    window.location.href = 'signin.html'; // Redirect to login page
                }
            }, 4000);
        })
        .catch(error => {
            console.error('Fetch Error:', error);

            // Show error message
            const errorBox = document.createElement('div');
            errorBox.style.position = 'fixed';
            errorBox.style.bottom = '20px';
            errorBox.style.right = '20px';
            errorBox.style.padding = '15px 30px';
            errorBox.style.color = '#fff';
            errorBox.style.backgroundColor = '#e74c3c';
            errorBox.style.borderRadius = '8px';
            errorBox.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.2)';
            errorBox.style.opacity = '1';
            errorBox.style.transition = 'opacity 0.5s ease';
            errorBox.textContent = 'Signup failed. Please try again.';

            document.body.appendChild(errorBox);

            // Remove error message after 4 seconds
            setTimeout(() => {
                errorBox.style.opacity = '0'; // Fade out
                setTimeout(() => errorBox.remove(), 500);
            }, 4000);
        });
});
