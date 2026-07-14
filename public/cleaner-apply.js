const params = new URLSearchParams(location.search);
const source = params.get('source') || 'Website';
document.querySelector('#sourceInput').value = source;
document.querySelector('#sourceLabel').textContent = source;

function checked(name){
  return [...document.querySelectorAll(`[data-name="${name}"] input:checked`)].map(x=>x.value);
}

document.querySelector('#applyForm').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const message = document.querySelector('#applyMessage');
  const data = Object.fromEntries(new FormData(form).entries());
  data.availability = checked('availability');
  data.services = checked('services');
  data.has_own_vehicle = form.elements.has_own_vehicle.checked;
  data.identity_verified = form.elements.identity_verified.checked;
  data.right_to_work_verified = form.elements.right_to_work_verified.checked;
  data.proof_of_address_verified = form.elements.proof_of_address_verified.checked;
  message.textContent = 'Sending your application...';
  message.className = 'form-message';
  try{
    const response = await fetch('/api/cleaner-applicants', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(data)
    });
    const result = await response.json();
    if(!response.ok) throw new Error(result.error || 'Could not submit application.');
    form.reset();
    document.querySelector('#sourceInput').value = source;
    message.textContent = 'Thanks — your cleaner application has been sent to Sparkles Cleaning Cambridge.';
    message.className = 'form-message success';
  }catch(error){
    message.textContent = error.message;
    message.className = 'form-message error';
  }
});
