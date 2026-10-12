import React from "react";
import ReactDOM from "react-dom/client";
import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { BrowserRouter } from "react-router-dom";
import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import App from "./App";

const BASE_PATH = (window as unknown as { __BASE_PATH__?: string }).__BASE_PATH__ || "";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MantineProvider defaultColorScheme="dark">
      <Notifications />
      <BrowserRouter basename={BASE_PATH}>
        <App />
      </BrowserRouter>
    </MantineProvider>
  </React.StrictMode>
);
