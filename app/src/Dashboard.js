import {LoadStatistic, PageContainer, SearchInput, useTitle} from "./components/Common";
import {useSearchFiles} from "./hooks/customHooks";
import React, {useContext, useState} from "react";
import {StatusContext} from "./contexts/contexts";
import {DownloadMenu} from "./components/Upload";
import {FilesSearchView} from "./components/Files";
import {Header, Segment, Statistic, StatisticGroup} from "./components/Theme";
import {Link} from "react-router-dom";
import {BandwidthProgressCombined, CPUUsageProgress} from "./components/admin/Status";
import {ProgressPlaceholder} from "./components/Placeholder";

export function Dashboard() {
    useTitle('Dashboard');

    const {searchStr, setSearchStr} = useSearchFiles();

    const {status} = useContext(StatusContext);
    const wrol_mode = status ? status['wrol_mode'] : null;

    const [downloadOpen, setDownloadOpen] = useState(false);
    const onDownloadOpen = (name) => setDownloadOpen(!!name);
    const downloads = <DownloadMenu onOpen={onDownloadOpen}/>;

    // Only show dashboard parts if not searching.
    let body;
    if (searchStr) {
        body = <FilesSearchView showLimit={true} showSelect={true} showSelectButton={true}/>;
    } else {
        body = <>
            {!wrol_mode && downloads}
            {/* Hide Status when user is starting a download */}
            {!downloadOpen && <DashboardStatus/>}
        </>;
    }

    return (<PageContainer>
            <SearchInput clearable
                         searchStr={searchStr}
                         onSubmit={setSearchStr}
                         size='large'
                         placeholder='Search Everywhere...'
                         actionIcon='search'
                         style={{marginBottom: '2em'}}
            />
            {body}
        </PageContainer>)
}

function DashboardStatus() {
    const {status} = useContext(StatusContext);

    let percent = 0;
    let load = {};
    let cores = 0;
    let pending_downloads = '?';
    if (status && status['cpu_info']) {
        percent = status['cpu_info']['percent'];
        load = status['load'];
        cores = status['cpu_info']['cores'];
    }

    const {downloads} = status;
    if (downloads) {
        pending_downloads = downloads['disabled'] ? 'x' : downloads['pending'];
    }

    return <Segment>
        <Link to='/admin/status'>
            <Header as='h2'>Status</Header>
            <CPUUsageProgress value={percent} label='CPU Usage'/>

            <Header as='h3'>Load</Header>
            <StatisticGroup size='mini'>
                <LoadStatistic label='1 Minute' value={load['minute_1']} cores={cores}/>
                <LoadStatistic label='5 Minute' value={load['minute_5']} cores={cores}/>
                <LoadStatistic label='15 Minute' value={load['minute_15']} cores={cores}/>
            </StatisticGroup>

            <Header as='h3'>Bandwidth</Header>
            {status && status['bandwidth'] ? status['bandwidth'].map(i => <BandwidthProgressCombined key={i['name']}
                                                                                                     bandwidth={i}/>) :
                <ProgressPlaceholder/>}
        </Link>

        <Link to='/admin'>
            <StatisticGroup size='mini'>
                <Statistic label='Downloading' value={pending_downloads}/>
            </StatisticGroup>
        </Link>

    </Segment>;
}
