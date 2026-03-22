const TZ = 'America/New_York';

export const formatDateTime = (dateStr) => {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleString('en-US', { timeZone: TZ });
};

export const formatDateShort = (dateStr, options = {}) => {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleDateString('en-US', { timeZone: TZ, ...options });
};

export const formatTime = (dateStr, options = {}) => {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleTimeString('en-US', { timeZone: TZ, ...options });
};
