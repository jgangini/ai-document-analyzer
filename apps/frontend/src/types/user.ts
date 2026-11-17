export interface User {
  user_id: number;
  username: string;
  name: string;
  last_name: string;
  email: string;
  modules: number[];
  group_id: number;
  group_name: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}
