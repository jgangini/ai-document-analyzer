export const profilesApi = {
  list: () =>
    Promise.resolve({
      data: {
        profiles: [
          { id: 'all', name: 'All' },
          { id: 'private', name: 'Private' },
        ],
      },
    }),
};
