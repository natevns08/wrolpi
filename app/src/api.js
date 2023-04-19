import {API_URI, ARCHIVES_API, DEFAULT_LIMIT, emptyToNull, OTP_API, VIDEOS_API} from "./components/Common";
import {toast} from "react-semantic-toasts-2";

function timeoutPromise(ms, promise) {
    // Create a timeout wrapper around a promise.  If the timeout is reached, throw an error.  Otherwise, return
    // the results of the promise.
    return new Promise((resolve, reject) => {
        const timeoutId = setTimeout(() => {
            reject(new Error("promise timeout"))
        }, ms);
        promise.then((res) => {
            clearTimeout(timeoutId);
            resolve(res);
        }, (err) => {
            clearTimeout(timeoutId);
            reject(err);
        });
    })
}

async function apiCall(url, method, body, ms = 60_000) {
    let init = {method};
    if (body !== undefined) {
        init.body = JSON.stringify(body);
    }

    // Create a fetch promise, this will be awaited by the timeout.
    let promise = fetch(url, init);

    try {
        // await the response or error.
        let response = await timeoutPromise(ms, promise);
        if (200 <= response.status && response.status < 300) {
            // Request was successful.
            return response;
        }
        // Request encountered an error.
        let copy = response.clone();
        let code = (await copy.json())['code'];
        if (response.status === 403 && code === 17) {
            toast({
                type: 'error',
                title: 'WROL Mode is enabled!',
                description: 'This functionality is disabled while WROL Mode is enabled!',
                time: 5000,
            });
        }
        return response;
    } catch (e) {
        // Timeout, or some other exception.
        console.error(e);
        throw e;
    }
}

// Convenience functions for API calls.
let apiGet = async (url) => {
    return await apiCall(url, 'GET')
};
let apiDelete = async (url) => {
    return await apiCall(url, 'DELETE')
};
let apiPost = async (url, body) => {
    return await apiCall(url, 'POST', body)
};
let apiPut = async (url, body) => {
    return await apiCall(url, 'PUT', body)
};
let apiPatch = async (url, body) => {
    return await apiCall(url, 'PATCH', body)
};

export async function updateChannel(id, channel) {
    channel = emptyToNull(channel);
    return await apiPut(`${VIDEOS_API}/channels/${id}`, channel);
}

export async function createChannel(channel) {
    channel = emptyToNull(channel);
    return await apiPost(`${VIDEOS_API}/channels`, channel);
}

export async function deleteChannel(channelId) {
    return apiDelete(`${VIDEOS_API}/channels/${channelId}`);
}

export async function getChannels() {
    let response = await apiGet(`${VIDEOS_API}/channels`);
    if (response.status === 200) {
        return (await response.json())['channels'];
    } else {
        toast({
            type: 'error',
            title: 'Unexpected server response',
            description: 'Failed to get channels.  See server logs.',
            time: 5000,
        });
    }
}

export async function getChannel(id) {
    let response = await apiGet(`${VIDEOS_API}/channels/${id}`);
    return (await response.json())['channel'];
}

export async function searchVideos(offset, limit, channelId, searchStr, order_by, tagNames, headline) {
    // Build a search query to retrieve a list of videos from the API
    offset = parseInt(offset || 0);
    limit = parseInt(limit || DEFAULT_LIMIT);
    let body = {offset, limit, order_by: order_by || 'rank'};

    if (searchStr) {
        body['search_str'] = searchStr;
    }
    if (channelId) {
        body['channel_id'] = parseInt(channelId);
    }
    if (tagNames) {
        body['tag_names'] = tagNames;
    }
    if (headline) {
        body['headline'] = true;
    }

    console.debug('searching videos', body);

    let response = await apiPost(`${VIDEOS_API}/search`, body);
    if (response.status === 200) {
        let data = await response.json();
        return [data['file_groups'], data['totals']['file_groups']];
    } else {
        toast({
            type: 'error',
            title: 'Unexpected server response',
            description: 'Failed to search videos.  See server logs.',
            time: 5000,
        });
        return [[], 0];
    }
}

export async function getVideo(video_id) {
    let response = await apiGet(`${VIDEOS_API}/video/${video_id}`);
    let data = await response.json();
    return [data['file_group'], data['prev'], data['next']];
}

export async function deleteVideos(videoIds) {
    const i = videoIds.join(',');
    let response = await apiDelete(`${VIDEOS_API}/video/${i}`);
    if (response.status !== 204) {
        toast({
            type: 'error',
            title: 'Unexpected server response',
            description: 'Failed to delete videos.  See server logs.',
            time: 5000,
        });
    }
}

export async function getDirectories(search_str) {
    let form_data = {'search_str': search_str || null};
    let response = await apiPost(`${API_URI}/files/directories`, form_data);
    if (response.status === 200) {
        return await response.json();
    }
    return [];
}

export async function getStatus() {
    let response = await apiGet(`${API_URI}/status`);
    if (response.status === 200) {
        return await response.json();
    } else {
        toast({
            type: 'error', title: 'Unexpected server response', description: 'Could not get server status', time: 5000,
        });
    }
}

export async function getSettings() {
    let response = await apiGet(`${API_URI}/settings`);
    if (response.status === 200) {
        return await response.json();
    } else {
        toast({
            type: 'error', title: 'Unexpected server response', description: 'Could not get settings', time: 5000,
        });
    }
}

export async function saveSettings(settings) {
    return await apiPatch(`${API_URI}/settings`, settings);
}

export async function getDownloads() {
    let response = await apiGet(`${API_URI}/download`);
    if (response.status === 200) {
        return await response.json();
    } else {
        toast({
            type: 'error', title: 'Unexpected server response', description: 'Could not get downloads', time: 5000,
        });
    }
}

export async function validateRegex(regex) {
    let response = await apiPost(`${API_URI}/valid_regex`, {regex});
    return (await response.json())['valid'];
}

export async function getVideosStatistics() {
    let response = await apiGet(`${VIDEOS_API}/statistics`);
    if (response.status === 200) {
        return (await response.json())['statistics'];
    } else {
        toast({
            type: 'error', title: 'Unexpected server response', description: 'Could not get statistics', time: 5000,
        });
    }
}

export async function downloadChannel(channelId) {
    let url = `${VIDEOS_API}/channels/download/${channelId}`;
    let response = await apiPost(url);
    if (response.status === 400) {
        const json = await response.json();
        if (json['code'] === 30) {
            toast({
                type: 'error',
                title: 'Cannot Download!',
                description: 'This channel does not have a download record.  Modify the frequency.',
                time: 5000,
            });
        }
    }
}

export async function refreshChannel(channelId) {
    let url = `${VIDEOS_API}/channels/refresh/${channelId}`;
    await fetch(url, {method: 'POST'});
}

export async function encryptOTP(otp, plaintext) {
    let body = {otp, plaintext};
    let response = await apiPost(`${OTP_API}/encrypt_otp`, body);
    if (response.status === 200) {
        return await response.json();
    } else {
        toast({
            type: 'error', title: 'Error!', description: 'Failed to encrypt OTP', time: 5000,
        });
    }
}

export async function decryptOTP(otp, ciphertext) {
    let body = {otp, ciphertext};
    let response = await apiPost(`${OTP_API}/decrypt_otp`, body);
    if (response.status === 200) {
        return await response.json();
    } else {
        toast({
            type: 'error', title: 'Error!', description: 'Failed to decrypt OTP', time: 5000,
        });
    }
}

export async function getCategories() {
    let response = await apiGet(`${API_URI}/inventory/categories`);
    if (response.status === 200) {
        return (await response.json())['categories'];
    } else {
        toast({
            type: 'error', title: 'Unexpected server response', description: 'Could not get categories', time: 5000,
        });
    }
}

export async function getBrands() {
    let response = await apiGet(`${API_URI}/inventory/brands`);
    if (response.status === 200) {
        return (await response.json())['brands'];
    } else {
        toast({
            type: 'error', title: 'Unexpected server response', description: 'Could not get brands', time: 5000,
        });
    }
}

export async function getInventories() {
    let response = await apiGet(`${API_URI}/inventory`);
    if (response.status === 200) {
        return (await response.json())['inventories'];
    } else {
        toast({
            type: 'error', title: 'Unexpected server response', description: 'Could not get inventories', time: 5000,
        });
    }
}

export async function getInventory(inventoryId) {
    let response = await apiGet(`${API_URI}/inventory/${inventoryId}`);
    if (response.status === 200) {
        return await response.json();
    } else {
        toast({
            type: 'error', title: 'Unexpected server response', description: 'Could not get inventory', time: 5000,
        });
    }
}

export async function saveInventory(inventory) {
    return await apiPost(`${API_URI}/inventory`, inventory);
}

export async function updateInventory(inventoryId, inventory) {
    delete inventory['id'];
    return await apiPut(`${API_URI}/inventory/${inventoryId}`, inventory);
}

export async function deleteInventory(inventoryId) {
    return await apiDelete(`${API_URI}/inventory/${inventoryId}`);
}

export async function getItems(inventoryId) {
    let response = await apiGet(`${API_URI}/inventory/${inventoryId}/item`);
    return await response.json();
}

export async function saveItem(inventoryId, item) {
    return await apiPost(`${API_URI}/inventory/${inventoryId}/item`, item);
}

export async function updateItem(itemId, item) {
    item = emptyToNull(item);
    return await apiPut(`${API_URI}/inventory/item/${itemId}`, item);
}

export async function deleteItems(itemIds) {
    let i = itemIds.join(',');
    await apiDelete(`${API_URI}/inventory/item/${i}`);
}

export async function deleteArchives(archiveIds) {
    let i = archiveIds.join(',');
    try {
        return await apiDelete(`${API_URI}/archive/${i}`);
    } catch (e) {
        console.error(e);
        toast({
            type: 'error', title: 'Unexpected server response', description: 'Unable to delete archives', time: 5000,
        });
    }
}

export async function searchArchives(offset, limit, domain, searchStr, order, tagNames, headline) {
    // Build a search query to retrieve a list of videos from the API
    offset = parseInt(offset || 0);
    limit = parseInt(limit || DEFAULT_LIMIT);
    let body = {offset, limit};
    if (domain) {
        body['domain'] = domain;
    }
    if (searchStr) {
        body['search_str'] = searchStr;
    }
    if (order) {
        body['order_by'] = order;
    }
    if (tagNames) {
        body['tag_names'] = tagNames;
    }
    if (headline) {
        body['headline'] = true;
    }

    console.debug('searching archives', body);
    let response = await apiPost(`${ARCHIVES_API}/search`, body);
    if (response.status === 200) {
        let data = await response.json();
        return [data['file_groups'], data['totals']['file_groups']];
    } else {
        toast({
            type: 'error',
            title: 'Unable to search archives',
            description: 'Cannot search archives.  See server logs.',
            time: 5000,
        });
        return [[], 0];
    }
}

export async function fetchDomains() {
    let response = await apiGet(`${ARCHIVES_API}/domains`);
    if (response.status === 200) {
        let data = await response.json();
        return [data['domains'], data['totals']['domains']];
    } else {
        toast({
            type: 'error',
            title: 'Domains Error',
            description: 'Unable to fetch Domains.  See server logs.',
            time: 5000,
        });
    }
}

export async function getArchive(archiveId) {
    const response = await apiGet(`${ARCHIVES_API}/${archiveId}`);
    if (response.status === 200) {
        const data = await response.json();
        return [data['file_group'], data['history']];
    } else {
        toast({
            type: 'error', title: 'Archive Error', description: 'Unable to get Archive.  See server logs.', time: 5000,
        });
    }
}

export async function postDownload(urls, downloader, frequency, sub_downloader, excludedURLs, destination, tagNames) {
    if (!downloader) {
        toast({
            type: 'error',
            title: 'Failed to submit download',
            description: 'downloader is required, but was not provided',
            time: 5000,
        })
        throw new Error('downloader is required, but was not provided');
    }

    let body = {
        urls: urls,
        downloader: downloader,
        frequency: frequency || null,
        excluded_urls: excludedURLs,
        destination: destination || null,
    };
    if (sub_downloader) {
        body['sub_downloader'] = sub_downloader;
    }
    if (tagNames) {
        body['tag_names'] = tagNames;
    }
    let response = await apiPost(`${API_URI}/download`, body);
    return response;
}

export async function killDownload(download_id) {
    let response = await apiPost(`${API_URI}/download/${download_id}/kill`);
    return response;
}

export async function killDownloads() {
    let response = await apiPost(`${API_URI}/download/kill`);
    return response;
}

export async function startDownloads() {
    let response = await apiPost(`${API_URI}/download/enable`);
    return response;
}

export async function getDownloaders() {
    try {
        let response = await apiGet(`${API_URI}/downloaders`);
        return await response.json();
    } catch (e) {
        return {downloaders: []};
    }
}

export async function deleteDownload(downloadId) {
    try {
        let response = await apiDelete(`${API_URI}/download/${downloadId}`);
        if (response.status !== 204) {
            toast({
                type: 'error',
                title: 'Unable to delete',
                description: 'Unable to delete the download.  See server logs.',
                time: 5000,
            });
        }
    } catch (e) {
        return null;
    }
}

export async function filesSearch(offset, limit, searchStr, mimetypes, model, tagNames, headline) {
    const body = {search_str: searchStr, offset: parseInt(offset), limit: parseInt(limit)};
    if (mimetypes) {
        body['mimetypes'] = mimetypes;
    }
    if (model) {
        body['model'] = model;
    }
    if (tagNames) {
        body['tag_names'] = tagNames;
    }
    if (headline) {
        body['headline'] = true;
    }
    console.debug('searching files', body);
    const response = await apiPost(`${API_URI}/files/search`, body);

    if (response.status === 200) {
        let data = await response.json();
        let [file_groups, total] = [data['file_groups'], data['totals']['file_groups']];
        return [file_groups, total];
    } else {
        toast({
            type: 'error',
            title: 'Unable to search files',
            description: 'Cannot search files.  See server logs.',
            time: 5000,
        });
        return [null, null];
    }
}

export async function refreshFiles() {
    return await apiPost(`${API_URI}/files/refresh`);
}

export async function refreshDirectoryFiles(directory) {
    let body = {paths: [directory]};
    try {
        return await apiPost(`${API_URI}/files/refresh`, body);
    } catch (e) {
        console.error(e);
        toast({
            type: 'error',
            title: 'Unable to refresh directory',
            description: 'Cannot refresh the files in the directory.  See server logs.',
            time: 5000,
        });
    }
}

export async function getFiles(directories) {
    console.debug(`getFiles ${directories}`);
    let body = {directories: directories || []};
    let response = await apiPost(`${API_URI}/files`, body);
    let {files} = await response.json();
    return files;
}

export async function deleteFile(file) {
    let body = {file: file};
    await apiPost(`${API_URI}/files/delete`, body);
}

export async function fetchFilesProgress() {
    const response = await apiGet(`${API_URI}/files/refresh_progress`);
    if (response.status === 200) {
        const json = await response.json();
        return json['progress'];
    }
}

export async function getHotspotStatus() {
    let response = await getSettings();
    return response['hotspot_status'];
}

export async function setHotspot(on) {
    let response;
    if (on) {
        response = await apiPost(`${API_URI}/hotspot/on`);
    } else {
        response = await apiPost(`${API_URI}/hotspot/off`);
    }
    if (response.status === 204) {
        return null;
    } else {
        let code = (await response.json())['code'];
        if (code === 34) {
            toast({
                type: 'error',
                title: 'Unsupported!',
                description: 'Hotspot is only supported on a Raspberry Pi!',
                time: 5000,
            });
        } else {
            toast({
                type: 'error', title: 'Error!', description: 'Could not modify hotspot.  See server logs.', time: 5000,
            });
        }
    }
}

export async function getThrottleStatus() {
    let response = await getSettings();
    return response['throttle_status'];
}

export async function setThrottle(on) {
    let response;
    if (on) {
        response = await apiPost(`${API_URI}/throttle/on`);
    } else {
        response = await apiPost(`${API_URI}/throttle/off`);
    }
    if (response.status === 204) {
        return null;
    } else {
        let code = (await response.json())['code'];
        if (code === 34) {
            toast({
                type: 'error',
                title: 'Unsupported!',
                description: 'Throttle is only supported on a Raspberry Pi!',
                time: 5000,
            });
        } else {
            toast({
                type: 'error', title: 'Error!', description: 'Could not modify throttle.  See server logs.', time: 5000,
            });
        }
    }
}

export async function getMapImportStatus() {
    let response = await apiGet(`${API_URI}/map/files`);
    if (response.status === 200) {
        return await response.json();
    } else {
        toast({
            type: 'error', title: 'Unexpected server response', description: 'Could not get import status', time: 5000,
        });
    }
}

export async function importMapFiles(paths) {
    let body = {'files': paths};
    let response = await apiPost(`${API_URI}/map/import`, body);
    if (response.status === 204) {
        return null;
    } else {
        toast({
            type: 'error', title: 'Error!', description: 'Could not start import!  See server logs.', time: 5000,
        });
    }
}

export async function clearCompletedDownloads() {
    let response = await apiPost(`${API_URI}/download/clear_completed`);
    if (response.status === 204) {
        return null
    } else {
        toast({
            type: 'error',
            title: 'Error!',
            description: 'Could not clear completed downloads!  See server logs.',
            time: 5000,
        });
    }
}

export async function clearFailedDownloads() {
    let response = await apiPost(`${API_URI}/download/clear_failed`);
    if (response.status === 204) {
        return null
    } else {
        toast({
            type: 'error',
            title: 'Error!',
            description: 'Could not clear failed downloads!  See server logs.',
            time: 5000,
        });
    }
}

export async function getStatistics() {
    let response = await apiGet(`${API_URI}/statistics`);
    if (response.status === 200) {
        const contents = await response.json();
        return contents;
    } else {
        toast({
            type: 'error', title: 'Error!', description: 'Unable to get file statistics', time: 5000,
        })
    }
}

export async function getEvents(after) {
    let uri = `${API_URI}/events/feed`;
    if (after) {
        uri = `${uri}?after=${encodeURIComponent(after)}`
    }
    let response = await apiGet(uri);
    if (response.status === 200) {
        return await response.json();
    }
}

export async function getTags() {
    let uri = `${API_URI}/tag`;
    let response = await apiGet(uri);
    if (response.status === 200) {
        const body = await response.json();
        return body['tags'];
    }
}

export async function addTag(fileGroup, name) {
    const body = {tag_name: name};

    const {id, primary_path, path} = fileGroup;
    if (id) {
        body['file_group_id'] = id;
    } else if (primary_path) {
        body['file_group_primary_path'] = primary_path;
    } else if (path) {
        body['file_group_primary_path'] = path;
    }

    const uri = `${API_URI}/files/tag`;
    let response = await apiPost(uri, body);
    if (response.status !== 201) {
        console.error('Failed to add tag');
    }
}

export async function removeTag(fileGroup, name) {
    const body = {tag_name: name};

    const {id, primary_path, path} = fileGroup;
    if (id) {
        body['file_group_id'] = id;
    } else if (primary_path) {
        body['file_group_primary_path'] = primary_path;
    } else if (path) {
        body['file_group_primary_path'] = path;
    }

    const uri = `${API_URI}/files/untag`;
    let response = await apiPost(uri, body)
    if (response.status !== 204) {
        console.error('Failed to remove tag');
    }
}

export async function saveTag(name, color, id) {
    const body = {name: name, color: color};
    let uri = `${API_URI}/tag`;
    if (id) {
        uri = `${uri}/${id}`;
    }
    let response = await apiPost(uri, body);
    if (id && response.status === 200) {
        toast({
            type: 'info', title: 'Saved tag', description: `Saved tag: ${name}`, time: 2000,
        });
    } else if (response.status === 201) {
        toast({
            type: 'info', title: 'Created new tag', description: `Created new tag: ${name}`, time: 2000,
        });
    } else {
        console.error('Failed to create new tag');
        toast({
            type: 'error', title: 'Error!', description: 'Unable to save tag', time: 5000,
        })
    }
}

export async function deleteTag(id, name) {
    const uri = `${API_URI}/tag/${id}`;
    let response = await apiDelete(uri);
    if (response.status === 400) {
        const content = await response.json();
        if (content['code'] === 38) {
            toast({
                type: 'error', title: 'Error!', description: content['message'], time: 5000,
            })
        }
    } else if (response.status !== 204) {
        console.error('Failed to delete tag');
        toast({
            type: 'error', title: 'Error!', description: `Unable to delete tag: ${name}`, time: 5000,
        })
    }
}

export async function fetchFile(path) {
    const uri = `${API_URI}/files/file`;
    const body = {file: path};
    const response = await apiPost(uri, body);
    if (response.status === 200) {
        const content = await response.json();
        return content['file'];
    } else {
        console.error('Unable to fetch file dict!  See client logs.');
    }
}

export async function sendNotification(message, url) {
    const body = {message, url};
    const response = await apiPost(`${API_URI}/notify`, body);
    if (response.status === 201) {
        toast({type: 'success', title: 'Shared', description: 'Your share was sent', time: 2000});
    } else {
        toast({type: 'error', title: 'Error', description: 'Your share failed to send!', time: 5000});
        console.error('Failed to share');
    }
}

export async function searchDirectories(name) {
    const body = {name: name || ''};
    const response = await apiPost(`${API_URI}/files/search_directories`, body);
    if (response.status === 204) {
        return [];
    } else if (response.status === 200) {
        const content = await response.json();
        return content;
    } else {
        toast({type: 'error', title: 'Error', description: 'Failed to search directories!', time: 5000});
    }
}

export async function uploadFiles(files, destination) {
    const data = new FormData();
    for (let i = 0; i < files.length; i++) {
        data.append('file', files[i]);
    }
    data.append('destination', destination);
    console.log(data);
}
