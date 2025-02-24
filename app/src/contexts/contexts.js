import React from "react";
import {createMedia} from "@artsy/fresnel";

export const ThemeContext = React.createContext({theme: null, i: {}});

export const StatusContext = React.createContext({});

export const AppMedia = createMedia({
    breakpoints: {
        mobile: 0, tablet: 700, computer: 1024,
    }
});
export const mediaStyles = AppMedia.createMediaStyle();
export const {Media, MediaContextProvider} = AppMedia;
