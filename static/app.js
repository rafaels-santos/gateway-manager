const form = document.querySelector('#connect');
const address = document.querySelector('#address');
const link = document.querySelector('#gateway');
address.addEventListener('input', () => {
  const value = address.value.trim();
  if (/^(?:\d{1,3}\.){3}\d{1,3}$/.test(value)) link.href = 'http://' + value + '/';
});
form.addEventListener('submit', event => {
  event.preventDefault();
  alert('A integração com este firmware ainda está em desenvolvimento. Nenhuma credencial foi enviada.');
});
